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

# Colunas SPED usadas na comparação — Bloco C (NF-e)
#   VL_ITEM  → agregado do C170 (VL_ITEM por item, somado por CHV_NFE)
#   VL_ICMS  → do C100 (cabeçalho da nota)
#   VL_IPI   → do C100
#   VL_PIS   → do C100
#   VL_COFINS→ do C100
COLS_SPED = ["VL_ITEM", "VL_ICMS", "VL_IPI", "VL_PIS", "VL_COFINS"]

# Colunas SPED usadas na comparação — Bloco D (CT-e / transporte)
#   VL_SERV   → do D100 (valor do serviço de transporte)
#   VL_PIS_D  → do D101 (PIS calculado no complemento)
#   VL_COFINS_D → do D105 (Cofins calculada no complemento)
COLS_SPED_D = ["VL_SERV", "VL_PIS_D", "VL_COFINS_D"]

# Colunas SPED usadas na comparação — Bloco F (F100)
#   VL_PIS    → do F100 (PIS calculado no registro)
#   VL_COFINS → do F100 (Cofins calculada no registro)
COLS_SPED_F100 = ["VL_PIS", "VL_COFINS"]

# Nomes das contas SAP que acumulam os créditos de regime misto (F100)
CONTA_PIS_RECUPERAR    = "PIS a Recuperar"
CONTA_COFINS_RECUPERAR = "COFINS a Recuperar"

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
    # Transporte (fretes pagos — entradas do Bloco D)
    "Fretes e Carretos":                 "VL_SERV_SAP",
    "Frete sobre Compras":               "VL_SERV_SAP",
    "Fretes sobre compras":              "VL_SERV_SAP",
    "Despesas com Fretes":               "VL_SERV_SAP",
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
    # Fretes pagos (CT-e aquisição — Bloco D)
    "Fretes e Carretos",
    "Frete sobre Compras",
    "Fretes sobre compras",
    "Despesas com Fretes",
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
    # Frete: sem conta canônica (usa a primeira encontrada)
    "VL_SERV_SAP":   ["Fretes e Carretos", "Frete sobre Compras", "Fretes sobre compras", "Despesas com Fretes"],
}

# Mapeamento delta → campo SAP (usado em gera_lancamentos_ajuste)
DELTA_PARA_CAMPO = {
    "DELTA_ICMS":   "VL_ICMS_SAP",
    "DELTA_PIS":    "VL_PIS_SAP",
    "DELTA_COFINS": "VL_COFINS_SAP",
    "DELTA_ITEM":   "VL_ITEM_SAP",
    # Bloco D
    "DELTA_SERV":       "VL_SERV_SAP",
    "DELTA_PIS_D":      "VL_PIS_SAP",
    "DELTA_COFINS_D":   "VL_COFINS_SAP",
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
    """
    c100 = dfs["C100"].copy()
    c170 = dfs["C170"].copy()

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

    df_saidas = (
        c100[c100["IND_OPER"] == "1"]
        .groupby(["NUM_DOC", "CHV_NFE"])[COLS_SPED]
        .sum()
        .reset_index()
    )

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


def _agregar_sped_d(dfs: dict) -> pd.DataFrame:
    """
    Agrega valores do Bloco D (aquisição de serviços de transporte).

    Os registros D100 sempre representam entradas (IND_OPER = "0").
    O valor do serviço vem do D100.VL_SERV; os créditos de PIS e Cofins
    vêm dos filhos D101.VL_PIS e D105.VL_COFINS, respectivamente.

    Retorna df com colunas: CHV_CTE, NUM_DOC, VL_SERV, VL_PIS_D, VL_COFINS_D.
    CSTs sem crédito (D101/D105 com VL_PIS/VL_COFINS = 0) são incluídos
    apenas para o valor do serviço; o crédito ficará zerado.
    """
    d100 = dfs.get("D100", pd.DataFrame())
    d101 = dfs.get("D101", pd.DataFrame())
    d105 = dfs.get("D105", pd.DataFrame())

    if d100.empty:
        return pd.DataFrame(columns=["CHV_CTE", "NUM_DOC"] + COLS_SPED_D)

    d100 = d100.copy()
    d100["VL_SERV"] = d100["VL_SERV"].apply(_to_float)

    # Agrega PIS por CT-e (D101)
    if not d101.empty:
        d101 = d101.copy()
        d101["_VL_PIS"] = d101["VL_PIS"].apply(_to_float)
        pis_por_cte = (
            d101.groupby("CHV_CTE")["_VL_PIS"]
            .sum()
            .reset_index()
            .rename(columns={"_VL_PIS": "VL_PIS_D"})
        )
    else:
        pis_por_cte = pd.DataFrame(columns=["CHV_CTE", "VL_PIS_D"])

    # Agrega Cofins por CT-e (D105)
    if not d105.empty:
        d105 = d105.copy()
        d105["_VL_COFINS"] = d105["VL_COFINS"].apply(_to_float)
        cofins_por_cte = (
            d105.groupby("CHV_CTE")["_VL_COFINS"]
            .sum()
            .reset_index()
            .rename(columns={"_VL_COFINS": "VL_COFINS_D"})
        )
    else:
        cofins_por_cte = pd.DataFrame(columns=["CHV_CTE", "VL_COFINS_D"])

    df = (
        d100[d100["IND_OPER"] == "0"]
        .groupby(["CHV_CTE", "NUM_DOC"])["VL_SERV"]
        .sum()
        .reset_index()
    )
    df = df.merge(pis_por_cte,    on="CHV_CTE", how="left")
    df = df.merge(cofins_por_cte, on="CHV_CTE", how="left")
    df["VL_PIS_D"]    = df["VL_PIS_D"].fillna(0.0)
    df["VL_COFINS_D"] = df["VL_COFINS_D"].fillna(0.0)

    return df


def _agregar_sped_f100(dfs: dict) -> pd.DataFrame:
    """
    Agrega F100 por COD_CTA (apenas IND_OPER=0 — despesas/entradas com
    crédito de PIS/COFINS em regime misto).

    Retorna df com colunas: COD_CTA, VL_PIS, VL_COFINS.
    """
    f100 = dfs.get("F100", pd.DataFrame())
    if f100.empty:
        return pd.DataFrame(columns=["COD_CTA"] + COLS_SPED_F100)

    f100 = f100.copy()
    f100["VL_PIS"]    = f100["VL_PIS"].apply(_to_float)
    f100["VL_COFINS"] = f100["VL_COFINS"].apply(_to_float)

    return (
        f100[f100["IND_OPER"] == "0"]
        .groupby("COD_CTA")[COLS_SPED_F100]
        .sum()
        .reset_index()
    )


def _agregar_sap_f100(df_contas: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega os créditos de PIS/COFINS a Recuperar do diário SAP relacionados
    a operações do Bloco F (regime misto não-NF-e).

    Critério de identificação automática: a 'Conta de contrapartida' de
    cada lançamento é um código contábil quando começa com dígito
    (ex: '4.01.03.03.0001'), e um código de parceiro quando começa com
    letra (ex: 'F04989').  Apenas os primeiros são de natureza F100.

    Lógica de valor líquido por conta de contrapartida:
      NET = sum(Débito) − sum(Crédito)
    Apenas entradas com NET > 0 são retornadas (créditos efetivos).

    Retorna df com colunas: COD_CTA, NOME_CONTA, VL_PIS_SAP, VL_COFINS_SAP.
    """
    # Lookup: código SAP → nome da conta (exclui as contas de recuperação)
    _excluir = {CONTA_PIS_RECUPERAR, CONTA_COFINS_RECUPERAR}
    _nome_lookup: dict = {}
    for _, r in df_contas.iterrows():
        cod  = str(r.get("Cta.contáb./cód.PN", "")).strip()
        nome = str(r.get("Cta.cont./Nome PN",  "")).strip()
        if cod and nome not in _excluir:
            _nome_lookup[cod] = nome

    def _net(conta_nome: str, campo: str) -> pd.DataFrame:
        linhas = df_contas[df_contas["Cta.cont./Nome PN"] == conta_nome]
        if linhas.empty:
            return pd.DataFrame(columns=["COD_CTA", campo])
        rows = []
        for contra, grp in linhas.groupby("Conta de contrapartida"):
            contra_str = str(contra).strip()
            # Aceita apenas contrapartidas que são códigos contábeis (começam
            # com dígito).  Códigos de parceiro (F00019…) são de NF-e/D100.
            if not contra_str[:1].isdigit():
                continue
            deb  = grp["Débito (MC)"].apply(_limpar_valor_sap).sum()
            cred = grp["Crédito (MC)"].apply(_limpar_valor_sap).sum()
            net  = round(deb - cred, 2)
            if net > 0:
                rows.append({"COD_CTA": contra_str, campo: net})
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["COD_CTA", campo])

    df_pis = _net(CONTA_PIS_RECUPERAR,    "VL_PIS_SAP")
    df_cof = _net(CONTA_COFINS_RECUPERAR, "VL_COFINS_SAP")

    if df_pis.empty and df_cof.empty:
        return pd.DataFrame(columns=["COD_CTA", "NOME_CONTA", "VL_PIS_SAP", "VL_COFINS_SAP"])

    df = df_pis.merge(df_cof, on="COD_CTA", how="outer")
    df["VL_PIS_SAP"]    = df["VL_PIS_SAP"].fillna(0.0)
    df["VL_COFINS_SAP"] = df["VL_COFINS_SAP"].fillna(0.0)
    df.insert(1, "NOME_CONTA", df["COD_CTA"].map(_nome_lookup).fillna(""))
    return df


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
    """
    df = _propagar_num_doc(df_sap)

    # [FIX-6] Filtro de filial
    if filtro_filial and "Nome da filial" in df.columns:
        df = df[df["Nome da filial"].str.contains(filtro_filial, na=False)]

    df = df[df["NUM_DOC"].notna()].copy()
    df["_campo"] = df["Cta.cont./Nome PN"].map(MAPA_CONTAS_SAP)
    df = df[df["_campo"].notna()].copy()
    df["_valor"] = df.apply(_valor_sap_correto, axis=1)

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
                    if campo in CONTA_CANONICA_SAIDA:
                        prioridade = CONTA_CANONICA_SAIDA[campo]
                        contas_presentes = set(grp_campo["Cta.cont./Nome PN"].unique())
                        for conta_pref in prioridade:
                            if conta_pref in contas_presentes:
                                grp_campo = grp_campo[grp_campo["Cta.cont./Nome PN"] == conta_pref]
                                break

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

def gera_lancamentos_so_sped(
    df_sap_raw: pd.DataFrame,
    so_sped_entrada: pd.DataFrame,
    so_sped_transporte: pd.DataFrame,
    so_sped_f100: pd.DataFrame,
) -> pd.DataFrame:
    """
    Gera lançamentos sugeridos para registros presentes apenas no SPED.

    Como não há lançamento SAP de referência, os códigos das contas de
    PIS/COFINS a Recuperar são extraídos de outros lançamentos do diário SAP.
    A conta de contrapartida fica em branco — deve ser preenchida manualmente
    antes da importação.

    Colunas do DataFrame retornado: mesmas de gera_lancamentos_ajuste, com
    Sentido = "Só SPED".
    """
    # Extrai código contábil das contas de recuperação do diário SAP
    _cod_pis = _cod_cofins = ""
    for _, r in df_sap_raw.iterrows():
        nome = str(r.get("Cta.cont./Nome PN", "")).strip()
        cod  = str(r.get("Cta.contáb./cód.PN", "")).strip()
        if nome == CONTA_PIS_RECUPERAR and not _cod_pis:
            _cod_pis = cod
        if nome == CONTA_COFINS_RECUPERAR and not _cod_cofins:
            _cod_cofins = cod
        if _cod_pis and _cod_cofins:
            break

    linhas = []

    def _lanc(vl_pis, vl_cofins, descricao, num_doc="", chv=""):
        vl_pis    = _to_float(vl_pis)
        vl_cofins = _to_float(vl_cofins)
        if abs(vl_pis) > TOLERANCIA:
            linhas.append({
                "Código da Conta":    _cod_pis,
                "Descrição da Conta": CONTA_PIS_RECUPERAR,
                "Débito":             round(vl_pis, 2),
                "Crédito":            None,
                "Descrição":          descricao,
                "Centro de Custo":    "",
                "Filial":             "",
                "NUM_DOC":            num_doc,
                "CHV_NFE":            chv,
                "Imposto":            "PIS",
                "DELTA":              None,
                "Sentido":            "Só SPED",
            })
        if abs(vl_cofins) > TOLERANCIA:
            linhas.append({
                "Código da Conta":    _cod_cofins,
                "Descrição da Conta": CONTA_COFINS_RECUPERAR,
                "Débito":             round(vl_cofins, 2),
                "Crédito":            None,
                "Descrição":          descricao,
                "Centro de Custo":    "",
                "Filial":             "",
                "NUM_DOC":            num_doc,
                "CHV_NFE":            chv,
                "Imposto":            "COFINS",
                "DELTA":              None,
                "Sentido":            "Só SPED",
            })

    # Bloco C — entradas (NF-e recebidas só no SPED)
    for _, row in so_sped_entrada.iterrows():
        num = str(row.get("NUM_DOC", ""))
        chv = str(row.get("CHV_NFE", ""))
        desc = f"NF {num}" if num else f"CHV {chv[:20]}"
        _lanc(row.get("VL_PIS", 0), row.get("VL_COFINS", 0), desc, num, chv)

    # Bloco D — transporte (CT-e só no SPED)
    for _, row in so_sped_transporte.iterrows():
        num = str(row.get("NUM_DOC", ""))
        chv = str(row.get("CHV_CTE", ""))
        desc = f"CT-e {num}" if num else f"CTE {chv[:20]}"
        _lanc(row.get("VL_PIS_D", 0), row.get("VL_COFINS_D", 0), desc, num, chv)

    # Bloco F — F100 só no SPED
    for _, row in so_sped_f100.iterrows():
        cod  = str(row.get("COD_CTA", ""))
        nome = str(row.get("NOME_CONTA", ""))
        desc = f"F100 {cod}" + (f" - {nome}" if nome else "")
        _lanc(row.get("VL_PIS", 0), row.get("VL_COFINS", 0), desc)

    return pd.DataFrame(linhas) if linhas else pd.DataFrame()


def compara_gera_diferenca(
    arquivo_sped: str,
    planilha_diario: str,
    filtro_filial: Optional[str] = None,
) -> dict:
    """
    Compara valores de impostos entre SPED (C100/C170 e D100/D101/D105)
    e planilha SAP, separando saídas, entradas NF-e e entradas CT-e.

    Parâmetros
    ----------
    arquivo_sped    : caminho do arquivo EFD-Contribuições (.txt).
    planilha_diario : caminho da planilha do diário SAP (.xlsx).
    filtro_filial   : substring do nome da filial no SAP (ex: 'Goiânia').
        Use quando o SPED cobre apenas um estabelecimento e o diário
        consolida múltiplas filiais. Se None, usa todas as linhas SAP.

    Chaves de cruzamento
    --------------------
    SPED Bloco C (saída)   → C100.NUM_DOC       × SAP Ref.3 (Linha)
    SPED Bloco C (entrada) → C100.CHV_NFE        × SAP CHV_NFE (via lookup)
    SPED Bloco D (CT-e)    → D100.CHV_CTE        × SAP CHV_CTE (via lookup NUM_DOC)

    Retorna dict com grupos de chaves:
    - DataFrames: 'divergencias_saida', 'divergencias_entrada',
                  'divergencias_transporte',
                  'ok_saida', 'ok_entrada', 'ok_transporte',
                  'so_sped_saida', 'so_sped_entrada', 'so_sped_transporte',
                  'so_sap_saida', 'so_sap_entrada', 'so_sap_transporte',
                  'lancamentos'.
    - JSON equivalente: sufixo '_json' em cada chave acima.
    """
    dfs    = extrai_dados_sped(arquivo_sped)
    df_sap = extrai_dados_planilha_sap(planilha_diario)

    # ── Bloco C ──────────────────────────────────────────────────────────────
    df_sped_saidas, df_sped_entradas  = _agregar_sped(dfs)
    df_sap_saidas,  df_sap_entradas   = _agregar_sap(df_sap, filtro_filial)

    # Enriquece df_sap_entradas com CHV_NFE do SPED C100 para cruzamento
    _chv_lookup = (
        dfs["C100"][dfs["C100"]["IND_OPER"] == "0"][["NUM_DOC", "CHV_NFE"]]
        .drop_duplicates("NUM_DOC")
    )
    df_sap_entradas = df_sap_entradas.merge(_chv_lookup, on="NUM_DOC", how="left")

    # ── Bloco D ──────────────────────────────────────────────────────────────
    df_sped_transp = _agregar_sped_d(dfs)

    # Agrega SAP para transporte: contas de frete (entradas) filtradas por
    # NUM_DOC que também aparecem no D100, depois enriquecidas com CHV_CTE.
    _chv_cte_lookup = pd.DataFrame()
    if not dfs["D100"].empty:
        _chv_cte_lookup = (
            dfs["D100"][["NUM_DOC", "CHV_CTE"]]
            .drop_duplicates("NUM_DOC")
        )

    # Usa _agregar_sap mas só com as contas de frete; depois faz lookup da chave
    df_sap_transp_saida, df_sap_transp_entrada = _agregar_sap(df_sap, filtro_filial)
    # Mantém apenas entradas com conta de frete (VL_SERV_SAP presente)
    df_sap_transp = df_sap_transp_entrada.copy()
    if "VL_SERV_SAP" not in df_sap_transp.columns:
        df_sap_transp["VL_SERV_SAP"] = 0.0
    # Remove linhas sem valor de frete
    df_sap_transp = df_sap_transp[df_sap_transp.get("VL_SERV_SAP", 0) != 0].copy()

    if not _chv_cte_lookup.empty:
        df_sap_transp = df_sap_transp.merge(_chv_cte_lookup, on="NUM_DOC", how="left")
    if "CHV_CTE" not in df_sap_transp.columns:
        df_sap_transp["CHV_CTE"] = pd.Series(dtype=str)

    # ── Comparações ──────────────────────────────────────────────────────────
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
    comparacoes_transporte = {
        "SERV":    ("VL_SERV",    "VL_SERV_SAP"),
        "PIS_D":   ("VL_PIS_D",   "VL_PIS_SAP"),
        "COFINS_D":("VL_COFINS_D","VL_COFINS_SAP"),
    }

    def _processar_lado(df_sped_agg, df_sap_agg, comparacoes, chave="NUM_DOC"):
        """
        Faz o merge, calcula deltas e separa divergências/ok/só-um-lado.

        chave="NUM_DOC"  → saídas (emissão própria, número único por empresa)
        chave="CHV_NFE"  → entradas NF-e
        chave="CHV_CTE"  → entradas CT-e (Bloco D)
        """
        df = pd.merge(df_sped_agg, df_sap_agg, on=chave, how="outer", indicator=True)

        if "NUM_DOC_x" in df.columns:
            df["NUM_DOC"] = df["NUM_DOC_x"].fillna(df["NUM_DOC_y"])
            df.drop(columns=["NUM_DOC_x", "NUM_DOC_y"], inplace=True)

        id_cols       = [chave] + (["NUM_DOC"] if chave != "NUM_DOC" and "NUM_DOC" in df.columns else [])
        chv_col       = [c for c in ["CHV_NFE", "CHV_CTE"] if c in df.columns and c != chave]
        sap_cols_pres = [c for c in df_sap_agg.columns if c != chave and c in df.columns and c not in id_cols]

        df_so_sped = (
            df[df["_merge"] == "left_only"]
            [id_cols + chv_col + [c for c in (COLS_SPED + COLS_SPED_D) if c in df.columns]]
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
    div_t, ok_t, so_sped_t, so_sap_t = _processar_lado(
        df_sped_transp, df_sap_transp, comparacoes_transporte, chave="CHV_CTE"
    )

    # ── Bloco F (F100 — demais operações sem nota fiscal) ────────────────────
    # Usa o mesmo df_sap já carregado; _agregar_sap_f100 filtra automaticamente
    # as contrapartidas contábeis (começam com dígito) das de parceiro (F…).
    df_sped_f100 = _agregar_sped_f100(dfs)
    df_sap_f100  = _agregar_sap_f100(df_sap)

    # Lookup código → nome a partir do próprio diário SAP
    _excluir_f = {CONTA_PIS_RECUPERAR, CONTA_COFINS_RECUPERAR}
    _nome_f100 = {
        str(r.get("Cta.contáb./cód.PN", "")).strip(): str(r.get("Cta.cont./Nome PN", "")).strip()
        for _, r in df_sap.iterrows()
        if str(r.get("Cta.cont./Nome PN", "")).strip() not in _excluir_f
    }

    comparacoes_f100 = {
        "PIS":    ("VL_PIS",    "VL_PIS_SAP"),
        "COFINS": ("VL_COFINS", "VL_COFINS_SAP"),
    }
    div_f, ok_f, so_sped_f, so_sap_f = _processar_lado(
        df_sped_f100,
        df_sap_f100,
        comparacoes_f100,
        chave="COD_CTA",
    )

    # Adiciona nome da conta em div, ok e só-SPED (só-SAP já tem NOME_CONTA
    # via _agregar_sap_f100)
    for _df in [div_f, ok_f, so_sped_f]:
        if not _df.empty and "COD_CTA" in _df.columns:
            _df.insert(1, "NOME_CONTA", _df["COD_CTA"].map(_nome_f100).fillna(""))

    # Lançamentos de ajuste (NF-e saídas + CT-e + F100)
    df_lanc_nf   = gera_lancamentos_ajuste(
        pd.concat([div_s, div_t], ignore_index=True),
        df_sap,
    )
    df_lanc_f100 = gera_lancamentos_ajuste_f100(div_f, df_sap)
    df_lanc = pd.concat([df_lanc_nf, df_lanc_f100], ignore_index=True)

    # Lançamentos sugeridos para registros só no SPED (sem contrapartida SAP)
    df_lanc_so_sped = gera_lancamentos_so_sped(
        df_sap,
        so_sped_e,
        so_sped_t,
        so_sped_f,
    )

    return {
        # DataFrames — Bloco C
        "divergencias_saida":       div_s,
        "divergencias_entrada":     div_e,
        "ok_saida":                 ok_s,
        "ok_entrada":               ok_e,
        "so_sped_saida":            so_sped_s,
        "so_sped_entrada":          so_sped_e,
        "so_sap_saida":             so_sap_s,
        "so_sap_entrada":           so_sap_e,
        # DataFrames — Bloco D (CT-e / transporte)
        "divergencias_transporte":  div_t,
        "ok_transporte":            ok_t,
        "so_sped_transporte":       so_sped_t,
        "so_sap_transporte":        so_sap_t,
        # DataFrames — Bloco F (F100)
        "divergencias_f100":        div_f,
        "ok_f100":                  ok_f,
        "so_sped_f100":             so_sped_f,
        "so_sap_f100":              so_sap_f,
        # Lançamentos consolidados
        "lancamentos":              df_lanc,
        "lancamentos_so_sped":      df_lanc_so_sped,
        # JSON equivalentes
        "divergencias_saida_json":      _df_para_json(div_s),
        "divergencias_entrada_json":    _df_para_json(div_e),
        "ok_saida_json":                _df_para_json(ok_s),
        "ok_entrada_json":              _df_para_json(ok_e),
        "so_sped_saida_json":           _df_para_json(so_sped_s),
        "so_sped_entrada_json":         _df_para_json(so_sped_e),
        "so_sap_saida_json":            _df_para_json(so_sap_s),
        "so_sap_entrada_json":          _df_para_json(so_sap_e),
        "divergencias_transporte_json": _df_para_json(div_t),
        "ok_transporte_json":           _df_para_json(ok_t),
        "so_sped_transporte_json":      _df_para_json(so_sped_t),
        "so_sap_transporte_json":       _df_para_json(so_sap_t),
        "divergencias_f100_json":       _df_para_json(div_f),
        "ok_f100_json":                 _df_para_json(ok_f),
        "so_sped_f100_json":            _df_para_json(so_sped_f),
        "so_sap_f100_json":             _df_para_json(so_sap_f),
        "lancamentos_json":             _df_para_json(df_lanc),
        "lancamentos_so_sped_json":     _df_para_json(df_lanc_so_sped),
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
            raw = row[delta_col]
            if pd.isna(raw):
                continue
            delta = round(float(raw), 2)
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


def gera_lancamentos_ajuste_f100(
    df_divergencias_f100: pd.DataFrame,
    df_sap_raw: pd.DataFrame,
) -> pd.DataFrame:
    """
    Gera lançamentos de ajuste para divergências F100 (Bloco F).

    Par de contas do ajuste:
      - Conta de recuperação : PIS a Recuperar / COFINS a Recuperar
      - Conta de contrapartida: a conta de despesa (COD_CTA do SPED)

    DELTA > 0 (SPED > SAP) → SAP a menor (complemento):
      Db PIS/COFINS a Recuperar / Cr Conta Despesa
    DELTA < 0 (SPED < SAP) → SAP a maior (estorno):
      Cr PIS/COFINS a Recuperar / Db Conta Despesa
    """
    if df_divergencias_f100.empty:
        return pd.DataFrame()

    # Metadados das contas de recuperação indexados por contra-account (COD_CTA)
    _meta_rec = {
        CONTA_PIS_RECUPERAR:    {},
        CONTA_COFINS_RECUPERAR: {},
    }
    _fallback = {
        CONTA_PIS_RECUPERAR:    None,
        CONTA_COFINS_RECUPERAR: None,
    }

    for _, r in df_sap_raw.iterrows():
        nome = str(r.get("Cta.cont./Nome PN", "")).strip()
        if nome not in _meta_rec:
            continue
        contra = str(r.get("Conta de contrapartida", "")).strip()
        if not contra[:1].isdigit():
            continue
        cod    = str(r.get("Cta.contáb./cód.PN", "")).strip()
        cc     = str(r["Centro de Custo"]) if pd.notna(r.get("Centro de Custo")) else ""
        filial = str(r.get("Nome da filial", "")) if pd.notna(r.get("Nome da filial")) else ""
        entry  = {"cod_conta": cod, "nome_conta": nome, "cc": cc, "filial": filial}

        if contra not in _meta_rec[nome]:
            _meta_rec[nome][contra] = entry
        if _fallback[nome] is None:
            _fallback[nome] = entry

    _DELTA_F100 = {
        "DELTA_PIS":    (CONTA_PIS_RECUPERAR,    "PIS"),
        "DELTA_COFINS": (CONTA_COFINS_RECUPERAR, "COFINS"),
    }

    linhas = []
    for _, row in df_divergencias_f100.iterrows():
        cod_cta  = str(row["COD_CTA"])
        nome_cta = str(row.get("NOME_CONTA", ""))

        for delta_col, (conta_rec, imposto) in _DELTA_F100.items():
            if delta_col not in row.index:
                continue
            delta = round(float(row[delta_col]), 2)
            if abs(delta) <= TOLERANCIA:
                continue

            meta_rec = _meta_rec[conta_rec].get(cod_cta) or _fallback[conta_rec]
            if meta_rec is None:
                continue

            sentido   = "SAP a maior (estorno)" if delta < 0 else "SAP a menor (complemento)"
            valor     = round(abs(delta), 2)
            desc      = f"F100 {cod_cta}" + (f" - {nome_cta}" if nome_cta else "")
            lado_rec  = "D" if delta > 0 else "C"
            lado_desp = "C" if delta > 0 else "D"

            for cod_c, nome_c, lado in [
                (meta_rec["cod_conta"], meta_rec["nome_conta"], lado_rec),
                (cod_cta,              nome_cta,                lado_desp),
            ]:
                linhas.append({
                    "Código da Conta":    cod_c,
                    "Descrição da Conta": nome_c,
                    "Débito":             valor if lado == "D" else None,
                    "Crédito":            valor if lado == "C" else None,
                    "Descrição":          desc,
                    "Centro de Custo":    meta_rec["cc"],
                    "Filial":             meta_rec["filial"],
                    "COD_CTA":            cod_cta,
                    "NOME_CONTA":         nome_cta,
                    "Imposto":            imposto,
                    "DELTA":              delta,
                    "Sentido":            sentido,
                })

    return pd.DataFrame(linhas)
