import json
import re as _re
from collections import defaultdict
from typing import Optional

import pandas as pd

from services.extrai_dados_sped import extrai_dados_sped
from services.extrai_dados_planilha_sap import extrai_dados_planilha_sap


# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

# Colunas SPED usadas na comparação
#   VL_ITEM  → agregado do C170 (VL_ITEM por item, somado por CHV_NFE)
#   VL_ICMS  → do C100 (cabeçalho da nota)
#   VL_IPI   → do C100
#   VL_PIS   → do C100
#   VL_COFINS→ do C100
COLS_SPED = ["VL_ITEM", "VL_ICMS", "VL_IPI", "VL_PIS", "VL_COFINS"]

# Mapeamento nome-de-conta-SAP → campo interno de comparação.
# Cada campo agrupa contas que representam o mesmo tributo, mas em
# naturezas opostas (saída × entrada).  A separação por natureza é
# feita em _agregar_sap usando CONTAS_SAIDA / CONTAS_ENTRADA.
MAPA_CONTAS_SAP = {
    # ICMS
    "( - ) ICMS":                       "VL_ICMS_SAP",
    "ICMS e Contribuições a Recolher":   "VL_ICMS_SAP",
    "ICMS e Contribuições a Recuperar":  "VL_ICMS_SAP",
    # PIS
    "( - ) PIS/PASEP":                   "VL_PIS_SAP",
    "PIS a Recolher":                    "VL_PIS_SAP",
    "PIS a Recuperar":                   "VL_PIS_SAP",
    # COFINS
    "( - ) COFINS":                      "VL_COFINS_SAP",
    "COFINS a Recolher":                 "VL_COFINS_SAP",
    "COFINS a Recuperar":                "VL_COFINS_SAP",
    # Mercadorias (saída)
    "Vendas de Mercadorias":             "VL_ITEM_SAP",
}

# Contas que representam saídas (IND_OPER = 1).
# Para essas contas o valor fiscal correto é o CRÉDITO do lançamento
# (exceto "( - ) ICMS" etc. que lança a DÉBITO, mas com mesmo valor
#  que o crédito espelho em "ICMS a Recolher" — veja FIX-2 abaixo).
CONTAS_SAIDA = {
    "( - ) COFINS",
    "( - ) ICMS",
    "( - ) PIS/PASEP",
    "COFINS a Recolher",
    "ICMS e Contribuições a Recolher",
    "PIS a Recolher",
    "Vendas de Mercadorias",
}

# Contas que representam entradas/créditos (IND_OPER = 0).
# O valor fiscal correto é o DÉBITO do lançamento.
CONTAS_ENTRADA = {
    "COFINS a Recuperar",
    "ICMS e Contribuições a Recuperar",
    "PIS a Recuperar",
}

# Conta canônica de saída por campo — usada para evitar duplicação.
# Para cada campo, apenas UMA das contas simétricas é contabilizada.
# Preferência: "a Recolher" (crédito direto do passivo).
# Se ausente, usa "( - )" (débito na receita, mesmo valor).
CONTA_CANONICA_SAIDA = {
    "VL_COFINS_SAP": ["COFINS a Recolher",                 "( - ) COFINS"],
    "VL_PIS_SAP":    ["PIS a Recolher",                    "( - ) PIS/PASEP"],
    "VL_ICMS_SAP":   ["ICMS e Contribuições a Recolher",   "( - ) ICMS"],
    "VL_ITEM_SAP":   ["Vendas de Mercadorias"],
}

# Mapeamento delta → campo SAP (usado em gera_lancamentos_ajuste)
DELTA_PARA_CAMPO = {
    "DELTA_ICMS":   "VL_ICMS_SAP",
    "DELTA_PIS":    "VL_PIS_SAP",
    "DELTA_COFINS": "VL_COFINS_SAP",
    "DELTA_ITEM":   "VL_ITEM_SAP",
}

TOLERANCIA = 0.05

_COD_PN = _re.compile(r"^[CF]\d+", _re.IGNORECASE)


# =============================================================================
# AUXILIARES
# =============================================================================

def _to_float(s) -> float:
    if not s or str(s).strip() == "":
        return 0.0
    try:
        return float(str(s).replace(",", "."))
    except ValueError:
        return 0.0


def _limpar_valor_sap(v) -> float:
    if pd.isna(v):
        return 0.0
    s = str(v).replace("R$ ", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _propagar_num_doc(df_sap: pd.DataFrame) -> pd.DataFrame:
    """
    Propaga o NUM_DOC (Ref.3) para cada linha de detalhe da planilha SAP.

    A planilha tem uma estrutura hierárquica: a linha de cabeçalho do
    lançamento (com Nº seq. preenchido) define o NUM_DOC; as linhas de
    detalhe abaixo herdam esse valor até o próximo cabeçalho.
    """
    df = df_sap.copy()
    df["NUM_DOC"] = None
    current_ref = None
    for idx, row in df.iterrows():
        if pd.notna(row["Nº seq."]):
            current_ref = None
        if pd.notna(row["Ref.3 (Linha)"]):
            try:
                current_ref = str(int(float(row["Ref.3 (Linha)"])))
            except (ValueError, TypeError):
                pass
        df.at[idx, "NUM_DOC"] = current_ref
    return df


def _valor_sap_correto(row: pd.Series) -> float:
    """
    Retorna o valor monetário correto de uma linha SAP com base na
    natureza da conta (saída → crédito; entrada → débito).

    [FIX-2] Correção da lógica anterior que usava indiscriminadamente
    'deb if deb > 0 else cred', sem considerar a natureza da conta.
    Isso causava valores zero em contas de saída que lançam só a débito
    (como "( - ) COFINS"), e também somava lados incorretos em entradas.
    """
    conta = str(row.get("Cta.cont./Nome PN", "")).strip()
    deb  = _limpar_valor_sap(row.get("Débito (MC)"))
    cred = _limpar_valor_sap(row.get("Crédito (MC)"))
    if conta in CONTAS_SAIDA:
        # Obrigação de saída: lançamento padrão é crédito no passivo.
        # "( - ) ICMS" etc. lançam a débito com mesmo valor — usamos o
        # lado que tiver valor (apenas um deles será > 0 por linha).
        return cred if cred > 0 else deb
    if conta in CONTAS_ENTRADA:
        # Crédito a recuperar: lançamento padrão é débito no ativo.
        return deb if deb > 0 else cred
    # Fallback para contas não classificadas
    return deb if deb > 0 else cred


# CSTs que não geram crédito de PIS/COFINS — entradas com esses CSTs
# em todos os itens não produzem lançamento de "a Recuperar" no SAP
# e devem ser excluídas da comparação de entradas.
CST_SEM_CREDITO = {"70", "71", "72", "73", "74", "75", "98", "99"}


def _agregar_sped(dfs: dict) -> tuple:
    """
    Agrega valores do SPED separando saídas de entradas.

    Retorna (df_saidas, df_entradas).

    Correções aplicadas:
    [FIX-3] Separação por IND_OPER antes de agregar.
    [FIX-4] VL_ITEM vem do C170, não do C100.
    [FIX-8] Entradas agrupadas por CHV_NFE (chave única do fornecedor).
            NUM_DOC de entrada não é único — fornecedores distintos podem
            usar o mesmo número de documento.
    [FIX-9] Entradas com todos os itens em CST sem crédito (70-75, 98-99)
            são excluídas. O SAP só lança "a Recuperar" quando há crédito
            efetivo, portanto essas notas gerariam falsos positivos.
    """
    c100 = dfs["C100"].copy()
    c170 = dfs["C170"].copy()

    # [FIX-4] Agrega VL_ITEM do C170 por CHV_NFE
    c170["_VL_ITEM"] = c170["VL_ITEM"].apply(_to_float)
    vl_item_por_chv = (
        c170.groupby("CHV_NFE")["_VL_ITEM"]
        .sum()
        .reset_index()
        .rename(columns={"_VL_ITEM": "VL_ITEM"})
    )

    for col in ["VL_ICMS", "VL_IPI", "VL_PIS", "VL_COFINS", "VL_MERC"]:
        c100[col] = c100[col].apply(_to_float)

    # Adiciona VL_ITEM do C170 ao C100 (join por CHV_NFE)
    c100 = c100.merge(vl_item_por_chv, on="CHV_NFE", how="left")
    c100["VL_ITEM"] = c100["VL_ITEM"].fillna(0.0)

    # [FIX-3] Saídas: agrupar por NUM_DOC (emissão própria, número único)
    df_saidas = (
        c100[c100["IND_OPER"] == "1"]
        .groupby(["NUM_DOC", "CHV_NFE"])[COLS_SPED]
        .sum()
        .reset_index()
    )

    # [FIX-8] + [FIX-9] Entradas: filtrar notas sem crédito e agrupar por CHV_NFE
    c170["_tem_credito"] = ~c170["CST_PIS"].isin(CST_SEM_CREDITO)
    chvs_com_credito = set(c170[c170["_tem_credito"]]["CHV_NFE"])

    c100_entradas = c100[
        (c100["IND_OPER"] == "0") &
        (c100["CHV_NFE"].isin(chvs_com_credito))
    ]
    df_entradas = (
        c100_entradas
        .groupby(["CHV_NFE", "NUM_DOC"])[COLS_SPED]
        .sum()
        .reset_index()
    )

    return df_saidas, df_entradas


def _agregar_sap(
    df_sap: pd.DataFrame,
    filtro_filial: Optional[str] = None,
) -> tuple:
    """
    Agrega valores do diário SAP separando saídas de entradas, e
    retorna (df_saidas_agg, df_entradas_agg).

    Parâmetros
    ----------
    df_sap : planilha do diário SAP (extrai_dados_planilha_sap).
    filtro_filial : substring do nome da filial a incluir (ex: 'Goiânia').
        Útil quando o SPED cobre apenas um estabelecimento e o diário
        consolida múltiplas filiais. Se None, usa todas as linhas.

    Correções aplicadas:
    [FIX-2] Valor correto por natureza de conta (veja _valor_sap_correto).
    [FIX-5] Eliminação de duplicação por contas simétricas.
        "( - ) COFINS" e "COFINS a Recolher" são os dois lados do mesmo
        lançamento contábil. A versão anterior somava os dois, duplicando
        o valor. Agora usamos apenas a conta canônica por campo/NF.
    [FIX-6] Filtro opcional por filial para alinhar o escopo com o SPED.
    """
    df = _propagar_num_doc(df_sap)

    # [FIX-6] Filtro de filial
    if filtro_filial and "Nome da filial" in df.columns:
        df = df[df["Nome da filial"].str.contains(filtro_filial, na=False)]

    df = df[df["NUM_DOC"].notna()].copy()
    df["_campo"] = df["Cta.cont./Nome PN"].map(MAPA_CONTAS_SAP)
    df = df[df["_campo"].notna()].copy()
    df["_valor"] = df.apply(_valor_sap_correto, axis=1)

    # [FIX-5] Para cada (NUM_DOC, campo), usar apenas a conta canônica de saída.
    # Prioridade definida em CONTA_CANONICA_SAIDA: "a Recolher" antes de "( - )".
    def _filtrar_canonico(grupo):
        campo = grupo["_campo"].iloc[0]
        conta_nome = grupo["Cta.cont./Nome PN"].iloc[0]

        if conta_nome in CONTAS_SAIDA and campo in CONTA_CANONICA_SAIDA:
            prioridade = CONTA_CANONICA_SAIDA[campo]
            contas_presentes = set(grupo["Cta.cont./Nome PN"].unique())
            for conta_pref in prioridade:
                if conta_pref in contas_presentes:
                    return grupo[grupo["Cta.cont./Nome PN"] == conta_pref]
        return grupo

    # Agrupa por (NUM_DOC, campo, conta) e aplica filtro canônico
    df_saidas_linhas  = df[df["Cta.cont./Nome PN"].isin(CONTAS_SAIDA)]
    df_entradas_linhas = df[df["Cta.cont./Nome PN"].isin(CONTAS_ENTRADA)]

    def _agg_sap(df_linhas: pd.DataFrame, natureza: str) -> pd.DataFrame:
            """
            natureza='saida'   → valor líquido = soma(Crédito) − soma(Débito)
            natureza='entrada' → valor líquido = soma(Débito)  − soma(Crédito)
            Estornos (lançamentos invertidos) se anulam automaticamente.
            """
            if df_linhas.empty:
                return pd.DataFrame(columns=["NUM_DOC"])

            rows = []
            for num_doc, grp_doc in df_linhas.groupby("NUM_DOC"):
                row = {"NUM_DOC": num_doc}
                for campo, grp_campo in grp_doc.groupby("_campo"):
                    # [FIX-5] Usa apenas a conta canônica para evitar duplicação
                    if campo in CONTA_CANONICA_SAIDA:
                        prioridade = CONTA_CANONICA_SAIDA[campo]
                        contas_presentes = set(grp_campo["Cta.cont./Nome PN"].unique())
                        for conta_pref in prioridade:
                            if conta_pref in contas_presentes:
                                grp_campo = grp_campo[grp_campo["Cta.cont./Nome PN"] == conta_pref]
                                break

                    # [FIX-7] Valor líquido (C − D ou D − C) para absorver estornos
                    total_deb  = grp_campo["Débito (MC)"].apply(_limpar_valor_sap).sum()
                    total_cred = grp_campo["Crédito (MC)"].apply(_limpar_valor_sap).sum()
                    if natureza == "saida":
                        row[campo] = round(total_cred - total_deb, 2)
                    else:
                        row[campo] = round(total_deb - total_cred, 2)
                rows.append(row)

            return pd.DataFrame(rows).fillna(0)

    return _agg_sap(df_saidas_linhas, "saida"), _agg_sap(df_entradas_linhas, "entrada")


# =============================================================================
# METADADOS (usados em gera_lancamentos_ajuste — sem alterações de lógica)
# =============================================================================

def _extrair_contrapartidas(df_sap: pd.DataFrame) -> dict:
    """
    Identifica dinamicamente a conta de contrapartida para lançamentos
    unilaterais (saídas: conta do cliente; entradas: Mercadorias para Revenda).
    """
    df = _propagar_num_doc(df_sap)
    if "Nome da filial" not in df.columns:
        df["Nome da filial"] = ""

    campos_saida   = {"VL_ITEM_SAP"}
    campos_entrada = {"VL_ICMS_SAP", "VL_PIS_SAP", "VL_COFINS_SAP"}
    resultado = {}

    for num_doc, grupo in df[df["NUM_DOC"].notna()].groupby("NUM_DOC"):
        def _cc(r):
            return str(r["Centro de Custo"]) if pd.notna(r["Centro de Custo"]) else ""
        def _filial(r):
            return str(r["Nome da filial"]) if pd.notna(r.get("Nome da filial")) else ""
        def _obs(r):
            return str(r["Observações"]) if pd.notna(r["Observações"]) else ""

        campos_presentes = {
            MAPA_CONTAS_SAP[str(r["Cta.cont./Nome PN"]).strip()]
            for _, r in grupo.iterrows()
            if str(r["Cta.cont./Nome PN"]).strip() in MAPA_CONTAS_SAP
        }

        for campo in campos_presentes:
            if campo in campos_saida:
                EXCLUIR = {"Mercadorias para Revenda - Peças", "Custo dos Produtos Vendidos"}
                nao_mapeadas_d = grupo[
                    ~grupo["Cta.cont./Nome PN"].isin(MAPA_CONTAS_SAP) &
                    ~grupo["Cta.cont./Nome PN"].isin(EXCLUIR) &
                    grupo["Débito (MC)"].apply(lambda v: _limpar_valor_sap(v) > 0)
                ]
                if nao_mapeadas_d.empty:
                    continue
                r = nao_mapeadas_d.iloc[0]
                resultado[(num_doc, campo)] = {
                    "cod_conta":  str(r["Cta.contáb./cód.PN"]).strip(),
                    "nome_conta": str(r["Cta.cont./Nome PN"]).strip(),
                    "lado": "D",
                    "cc":     _cc(r),
                    "filial": _filial(r),
                    "obs":    _obs(r),
                }

            elif campo in campos_entrada:
                mercadorias = grupo[
                    grupo["Cta.cont./Nome PN"].astype(str).str.strip()
                    == "Mercadorias para Revenda - Peças"
                ]
                if mercadorias.empty:
                    continue
                r = mercadorias.iloc[0]
                deb = _limpar_valor_sap(r["Débito (MC)"])
                resultado[(num_doc, campo)] = {
                    "cod_conta":  str(r["Cta.contáb./cód.PN"]).strip(),
                    "nome_conta": str(r["Cta.cont./Nome PN"]).strip(),
                    "lado": "D" if deb > 0 else "C",
                    "cc":     _cc(r),
                    "filial": _filial(r),
                    "obs":    _obs(r),
                }

    return resultado


def _extrair_metadados_contas(df_sap: pd.DataFrame) -> dict:
    """
    Extrai metadados (código, lado, CC, filial, obs) de cada conta de
    imposto mapeada, por (num_doc, campo). Usado em gera_lancamentos_ajuste.
    """
    df = _propagar_num_doc(df_sap)
    if "Nome da filial" not in df.columns:
        df["Nome da filial"] = ""

    vistos = set()
    idx = defaultdict(list)

    for _, r in df[df["NUM_DOC"].notna()].iterrows():
        conta = str(r["Cta.cont./Nome PN"]).strip()
        if conta not in MAPA_CONTAS_SAP:
            continue
        campo   = MAPA_CONTAS_SAP[conta]
        num_doc = r["NUM_DOC"]
        cod     = str(r["Cta.contáb./cód.PN"]).strip()
        deb     = _limpar_valor_sap(r["Débito (MC)"])
        lado    = "D" if deb > 0 else "C"
        key     = (num_doc, campo, cod, lado)
        if key in vistos:
            continue
        vistos.add(key)

        idx[(num_doc, campo)].append({
            "cod_conta":  cod,
            "nome_conta": conta,
            "lado":       lado,
            "cc":         str(r["Centro de Custo"]) if pd.notna(r["Centro de Custo"]) else "",
            "filial":     str(r["Nome da filial"])  if pd.notna(r.get("Nome da filial")) else "",
            "obs":        str(r["Observações"])      if pd.notna(r["Observações"])       else "",
        })

    return idx


# =============================================================================
# SERIALIZAÇÃO
# =============================================================================

def _df_para_json(df: pd.DataFrame) -> list:
    """Converte DataFrame para lista de dicts JSON-safe."""
    return json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))


# =============================================================================
# FUNÇÕES PRINCIPAIS
# =============================================================================

def compara_gera_diferenca(
    arquivo_sped: str,
    planilha_diario: str,
    filtro_filial: Optional[str] = None,
) -> dict:
    """
    Compara valores de impostos entre SPED (C100/C170) e planilha SAP,
    separando saídas de entradas.

    Parâmetros
    ----------
    arquivo_sped    : caminho do arquivo EFD-Contribuições (.txt).
    planilha_diario : caminho da planilha do diário SAP (.xlsx).
    filtro_filial   : substring do nome da filial no SAP (ex: 'Goiânia').
        Use quando o SPED cobre apenas um estabelecimento e o diário
        consolida múltiplas filiais. Se None, usa todas as linhas SAP.

    Chave de cruzamento
    -------------------
    SPED → C100.NUM_DOC
    SAP  → Ref.3 (Linha) (= número da NF)

    Retorna dict com dois grupos de chaves:
    - DataFrames: 'divergencias_saida', 'divergencias_entrada',
                  'ok_saida', 'ok_entrada',
                  'so_sped_saida', 'so_sped_entrada',
                  'so_sap_saida', 'so_sap_entrada',
                  'lancamentos'.
    - JSON equivalente: sufixo '_json' em cada chave acima.

    Correções aplicadas nesta versão
    ---------------------------------
    [FIX-2] Valor SAP extraído pelo lado correto por natureza de conta.
    [FIX-3] SPED separado por IND_OPER antes de cruzar com SAP.
    [FIX-4] VL_ITEM vem do C170, não de VL_MERC do C100.
    [FIX-5] Contas simétricas (ex: "COFINS a Recolher" + "( - ) COFINS")
            usadas apenas uma vez por nota, eliminando duplicação de 2×.
    [FIX-6] Filtro opcional de filial no SAP.
    """
    dfs    = extrai_dados_sped(arquivo_sped)
    df_sap = extrai_dados_planilha_sap(planilha_diario)

    # Agrega SPED e SAP separados por natureza
    df_sped_saidas, df_sped_entradas  = _agregar_sped(dfs)
    df_sap_saidas,  df_sap_entradas   = _agregar_sap(df_sap, filtro_filial)

    # Enriquece df_sap_entradas com CHV_NFE do SPED C100 para permitir
    # o cruzamento por chave (evita colisão de NUM_DOC entre fornecedores)
    _chv_lookup = (
        dfs["C100"][dfs["C100"]["IND_OPER"] == "0"][["NUM_DOC", "CHV_NFE"]]
        .drop_duplicates("NUM_DOC")
    )
    df_sap_entradas = df_sap_entradas.merge(_chv_lookup, on="NUM_DOC", how="left")

    comparacoes_saida = {
        "ICMS":   ("VL_ICMS",   "VL_ICMS_SAP"),
        "PIS":    ("VL_PIS",    "VL_PIS_SAP"),
        "COFINS": ("VL_COFINS", "VL_COFINS_SAP"),
        "ITEM":   ("VL_ITEM",   "VL_ITEM_SAP"),
    }
    comparacoes_entrada = {
        "ICMS":   ("VL_ICMS",   "VL_ICMS_SAP"),
        "PIS":    ("VL_PIS",    "VL_PIS_SAP"),
        "COFINS": ("VL_COFINS", "VL_COFINS_SAP"),
    }

    def _processar_lado(df_sped_agg, df_sap_agg, comparacoes, chave="NUM_DOC"):
        """
        Faz o merge, calcula deltas e separa divergências/ok/só-um-lado.

        chave="NUM_DOC"  → saídas (emissão própria, número único por empresa)
        chave="CHV_NFE"  → entradas (NF de fornecedor; NUM_DOC não é único pois
                           fornecedores distintos podem usar o mesmo número)
        [FIX-8] Entradas cruzadas por CHV_NFE para evitar colisão de NUM_DOC.
        """
        df = pd.merge(df_sped_agg, df_sap_agg, on=chave, how="outer", indicator=True)

        sap_cols_pres = [c for c in df_sap_agg.columns if c != chave and c in df.columns]
        id_cols       = [chave] + (["NUM_DOC"] if chave != "NUM_DOC" and "NUM_DOC" in df.columns else [])
        chv_col       = ["CHV_NFE"] if "CHV_NFE" in df.columns and "CHV_NFE" != chave else []

        df_so_sped = (
            df[df["_merge"] == "left_only"]
            [id_cols + chv_col + [c for c in COLS_SPED if c in df.columns]]
            .reset_index(drop=True)
        )
        df_so_sap = (
            df[df["_merge"] == "right_only"]
            [id_cols + sap_cols_pres]
            .reset_index(drop=True)
        )

        df_ambos = df[df["_merge"] == "both"].copy()
        delta_cols = []
        for imposto, (col_sped, col_sap) in comparacoes.items():
            v_sped = df_ambos[col_sped].fillna(0) if col_sped in df_ambos.columns else 0
            v_sap  = df_ambos[col_sap].fillna(0)  if col_sap  in df_ambos.columns else 0
            dc = f"DELTA_{imposto}"
            df_ambos[dc] = (v_sped - v_sap).round(2)
            delta_cols.append(dc)

        sped_cols = [v[0] for v in comparacoes.values() if v[0] in df_ambos.columns]
        sap_cols  = [v[1] for v in comparacoes.values() if v[1] in df_ambos.columns]

        mask = df_ambos[delta_cols].abs().max(axis=1) > TOLERANCIA

        df_div = (
            df_ambos[mask]
            [id_cols + chv_col + sped_cols + sap_cols + delta_cols]
            .reset_index(drop=True)
        )
        df_ok = (
            df_ambos[~mask]
            [id_cols + chv_col + sped_cols + sap_cols]
            .reset_index(drop=True)
        )

        return df_div, df_ok, df_so_sped, df_so_sap

    div_s, ok_s, so_sped_s, so_sap_s = _processar_lado(
        df_sped_saidas, df_sap_saidas, comparacoes_saida, chave="NUM_DOC"
    )
    div_e, ok_e, so_sped_e, so_sap_e = _processar_lado(
        df_sped_entradas, df_sap_entradas, comparacoes_entrada, chave="CHV_NFE"
    )

    # Lançamentos de ajuste (baseados nas divergências de saída, que têm CHV_NFE)
    df_lanc = gera_lancamentos_ajuste(div_s, df_sap)

    return {
        # DataFrames
        "divergencias_saida":    div_s,
        "divergencias_entrada":  div_e,
        "ok_saida":              ok_s,
        "ok_entrada":            ok_e,
        "so_sped_saida":         so_sped_s,
        "so_sped_entrada":       so_sped_e,
        "so_sap_saida":          so_sap_s,
        "so_sap_entrada":        so_sap_e,
        "lancamentos":           df_lanc,
        # JSON equivalente
        "divergencias_saida_json":   _df_para_json(div_s),
        "divergencias_entrada_json": _df_para_json(div_e),
        "ok_saida_json":             _df_para_json(ok_s),
        "ok_entrada_json":           _df_para_json(ok_e),
        "so_sped_saida_json":        _df_para_json(so_sped_s),
        "so_sped_entrada_json":      _df_para_json(so_sped_e),
        "so_sap_saida_json":         _df_para_json(so_sap_s),
        "so_sap_entrada_json":       _df_para_json(so_sap_e),
        "lancamentos_json":          _df_para_json(df_lanc),
    }


def gera_lancamentos_ajuste(
    df_divergencias: pd.DataFrame,
    df_sap_raw: pd.DataFrame,
) -> pd.DataFrame:
    """
    Gera lançamentos de ajuste no formato de importação SAP para todas
    as notas com divergência de saída.

    Lógica do ajuste (SPED é considerado correto):
      DELTA = SPED - SAP
      DELTA < 0 → SAP a maior → estorno: inverte os lados
      DELTA > 0 → SAP a menor → complemento: mantém os lados
      Valor do lançamento = |DELTA|

    Contas e metadados vêm exclusivamente da planilha SAP.

    Colunas do DataFrame retornado:
      Formato importação : Código da Conta, Descrição da Conta,
                           Débito, Crédito, Descrição, Centro de Custo, Filial
      Rastreabilidade    : NUM_DOC, CHV_NFE, Imposto, DELTA, Sentido
    """
    idx_meta          = _extrair_metadados_contas(df_sap_raw)
    idx_contrapartida = _extrair_contrapartidas(df_sap_raw)
    linhas = []

    for _, row in df_divergencias.iterrows():
        num_doc = str(row["NUM_DOC"])
        chv     = row.get("CHV_NFE", "")

        for delta_col, campo in DELTA_PARA_CAMPO.items():
            if delta_col not in row.index:
                continue
            delta = round(float(row[delta_col]), 2)
            if abs(delta) <= TOLERANCIA:
                continue

            contas = idx_meta.get((num_doc, campo), [])
            if not contas:
                continue

            sentido = "SAP a maior (estorno)" if delta < 0 else "SAP a menor (complemento)"
            valor   = round(abs(delta), 2)

            lados_ajuste = [
                ("C" if c["lado"] == "D" else "D") if delta < 0 else c["lado"]
                for c in contas
            ]

            tem_debito  = any(l == "D" for l in lados_ajuste)
            tem_credito = any(l == "C" for l in lados_ajuste)

            if not tem_debito or not tem_credito:
                cp = idx_contrapartida.get((num_doc, campo))
                if cp:
                    lado_principal = lados_ajuste[0] if lados_ajuste else ("C" if delta > 0 else "D")
                    lado_cp = "C" if lado_principal == "D" else "D"
                    contas       = list(contas) + [cp]
                    lados_ajuste = lados_ajuste + [lado_cp]

            for c, lado_ajuste in zip(contas, lados_ajuste):
                linhas.append({
                    "Código da Conta":    c["cod_conta"],
                    "Descrição da Conta": c["nome_conta"],
                    "Débito":             valor if lado_ajuste == "D" else None,
                    "Crédito":            valor if lado_ajuste == "C" else None,
                    "Descrição":          f"NF {num_doc} - {c['obs']}" if c["obs"] else f"NF {num_doc}",
                    "Centro de Custo":    c["cc"],
                    "Filial":             c["filial"],
                    "NUM_DOC":            num_doc,
                    "CHV_NFE":            chv,
                    "Imposto":            delta_col.replace("DELTA_", ""),
                    "DELTA":              delta,
                    "Sentido":            sentido,
                })

    return pd.DataFrame(linhas)
