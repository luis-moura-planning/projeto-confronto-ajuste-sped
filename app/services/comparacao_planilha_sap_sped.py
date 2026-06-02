import json
import pandas as pd
from collections import defaultdict

from services.extrai_dados_sped import extrai_dados_sped
from services.extrai_dados_planilha_sap import extrai_dados_planilha_sap


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────────────────────────────────────

COLS_SPED = ["VL_ITEM", "VL_ICMS", "VL_IPI", "VL_PIS", "VL_COFINS"]

MAPA_CONTAS_SAP = {
    "( - ) ICMS":                       "VL_ICMS_SAP",
    "ICMS e Contribuições a Recolher":   "VL_ICMS_SAP",
    "ICMS e Contribuições a Recuperar":  "VL_ICMS_SAP",
    "( - ) PIS/PASEP":                   "VL_PIS_SAP",
    "PIS a Recolher":                    "VL_PIS_SAP",
    "PIS a Recuperar":                   "VL_PIS_SAP",
    "( - ) COFINS":                      "VL_COFINS_SAP",
    "COFINS a Recolher":                 "VL_COFINS_SAP",
    "COFINS a Recuperar":                "VL_COFINS_SAP",
    "Vendas de Mercadorias":             "VL_ITEM_SAP",
}

# Mapa de delta → campo SAP correspondente
DELTA_PARA_CAMPO = {
    "DELTA_ICMS":   "VL_ICMS_SAP",
    "DELTA_PIS":    "VL_PIS_SAP",
    "DELTA_COFINS": "VL_COFINS_SAP",
    "DELTA_ITEM":   "VL_ITEM_SAP",
}

TOLERANCIA = 0.05


# ─────────────────────────────────────────────────────────────────────────────
# AUXILIARES
# ─────────────────────────────────────────────────────────────────────────────

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
        return float(s)
    except ValueError:
        return 0.0



def _propagar_num_doc(df_sap: pd.DataFrame) -> pd.DataFrame:
    """Propaga o NUM_DOC (Ref.3) para cada linha de detalhe da planilha SAP."""
    df = df_sap.copy()
    df["NUM_DOC"] = None
    current_ref = None
    for idx, row in df.iterrows():
        if pd.notna(row["Nº seq."]):
            current_ref = None
        if pd.notna(row["Ref.3 (Linha)"]):
            try:
                current_ref = str(int(float(str(row["Ref.3 (Linha)"]).replace(".", "").replace(",", "").strip())))
            except (ValueError, TypeError):
                pass  # ignora CNPJs e outros valores não numéricos
        df.at[idx, "NUM_DOC"] = current_ref
    return df


def _agregar_sped(dfs: dict) -> pd.DataFrame:
    df_c170 = dfs["C170"].copy()
    for col in COLS_SPED:
        df_c170[col] = df_c170[col].apply(_to_float)
    df_agg = df_c170.groupby("CHV_NFE")[COLS_SPED].sum().reset_index()
    df_c100 = dfs["C100"][["NUM_DOC", "CHV_NFE"]].drop_duplicates()
    return df_agg.merge(df_c100, on="CHV_NFE", how="left")


def _agregar_sap(df_sap: pd.DataFrame) -> pd.DataFrame:
    df = _propagar_num_doc(df_sap)
    rows = []
    for num_doc, grupo in df[df["NUM_DOC"].notna()].groupby("NUM_DOC"):
        row = {"NUM_DOC": num_doc}
        for _, r in grupo.iterrows():
            conta = str(r["Cta.cont./Nome PN"]).strip()
            if conta in MAPA_CONTAS_SAP:
                campo = MAPA_CONTAS_SAP[conta]
                deb  = _limpar_valor_sap(r["Débito (MC)"])
                cred = _limpar_valor_sap(r["Crédito (MC)"])
                row[campo] = row.get(campo, 0.0) + (deb if deb > 0 else cred)
        rows.append(row)
    return pd.DataFrame(rows).fillna(0)


import re as _re

# Padrão de código de parceiro de negócio (cliente C... / fornecedor F...)
_COD_PN = _re.compile(r'^[CF]\d+', _re.IGNORECASE)


def _extrair_contrapartidas(df_sap: pd.DataFrame) -> dict:
    """
    Para cada (num_doc, campo_imposto) que pode gerar lançamentos unilaterais
    (Vendas de Mercadorias só a C; contas a Recuperar só a D), identifica
    dinamicamente a conta de contrapartida na planilha SAP.

    Lógica por tipo:
    - VL_ITEM_SAP (Vendas de Mercadorias, saída):
        contrapartida = conta do CLIENTE (Cx, qualquer lado — usa o primeiro encontrado)
    - VL_ICMS_SAP / VL_PIS_SAP / VL_COFINS_SAP (a Recuperar, entrada):
        contrapartida = "Mercadorias para Revenda - Peças"

    A contrapartida é sempre registrada para esses campos, independente dos
    lados presentes na planilha — a função gera_lancamentos_ajuste só a usa
    quando o conjunto de contas mapeadas não produz D e C.

    Retorna dict: (num_doc, campo_imposto) → dict de conta contrapartida.
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
            return str(r["Nome da filial"]) if pd.notna(r["Nome da filial"]) else ""
        def _obs(r):
            return str(r["Observações"]) if pd.notna(r["Observações"]) else ""

        # Campos de imposto presentes neste grupo
        campos_presentes = {
            MAPA_CONTAS_SAP[str(r["Cta.cont./Nome PN"]).strip()]
            for _, r in grupo.iterrows()
            if str(r["Cta.cont./Nome PN"]).strip() in MAPA_CONTAS_SAP
        }

        for campo in campos_presentes:
            if campo in campos_saida:
                # Contrapartida de Vendas de Mercadorias (sempre a C):
                # busca a primeira conta não mapeada que esteja a Débito no grupo,
                # excluindo contas de custo/estoque que são contrapartidas internas
                EXCLUIR_CONTRAPARTIDA = {"Mercadorias para Revenda - Peças", "Custo dos Produtos Vendidos"}
                nao_mapeadas_d = grupo[
                    ~grupo["Cta.cont./Nome PN"].isin(MAPA_CONTAS_SAP) &
                    ~grupo["Cta.cont./Nome PN"].isin(EXCLUIR_CONTRAPARTIDA) &
                    grupo["Débito (MC)"].apply(lambda v: _limpar_valor_sap(v) > 0)
                ]
                if nao_mapeadas_d.empty:
                    continue
                r = nao_mapeadas_d.iloc[0]
                resultado[(num_doc, campo)] = {
                    "cod_conta":  str(r["Cta.contáb./cód.PN"]).strip(),
                    "nome_conta": str(r["Cta.cont./Nome PN"]).strip(),
                    "lado":       "D",
                    "cc":         _cc(r),
                    "filial":     _filial(r),
                    "obs":        _obs(r),
                }

            elif campo in campos_entrada:
                # Contrapartida: Mercadorias para Revenda - Peças
                mercadorias = grupo[
                    grupo["Cta.cont./Nome PN"].astype(str).str.strip() == "Mercadorias para Revenda - Peças"
                ]
                if mercadorias.empty:
                    continue
                r = mercadorias.iloc[0]
                deb = _limpar_valor_sap(r["Débito (MC)"])
                resultado[(num_doc, campo)] = {
                    "cod_conta":  str(r["Cta.contáb./cód.PN"]).strip(),
                    "nome_conta": str(r["Cta.cont./Nome PN"]).strip(),
                    "lado":       "D" if deb > 0 else "C",
                    "cc":         _cc(r),
                    "filial":     _filial(r),
                    "obs":        _obs(r),
                }

    return resultado


def _extrair_metadados_contas(df_sap: pd.DataFrame) -> dict:
    """
    Lê a planilha SAP e extrai os metadados de cada conta de imposto por nota:
    código, nome, lado (D/C), centro de custo, filial e observação.

    As contas são dinâmicas — vêm exclusivamente da planilha do cliente,
    sem nenhum valor fixo no código.

    Retorna dict: (num_doc, campo_imposto) → lista de dicts de conta.
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
            "filial":     str(r["Nome da filial"])  if pd.notna(r["Nome da filial"])  else "",
            "obs":        str(r["Observações"])      if pd.notna(r["Observações"])      else "",
        })

    return idx


# ─────────────────────────────────────────────────────────────────────────────
# SERIALIZAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def _df_para_json(df: pd.DataFrame) -> list:
    """
    Converte DataFrame para lista de dicts JSON-safe.
    NaN e None viram null; tipos pandas (int64, float64) são normalizados
    automaticamente pelo to_json do pandas antes do parse.
    """
    return json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÕES PRINCIPAIS
# ─────────────────────────────────────────────────────────────────────────────

def compara_gera_diferenca(arquivo_sped: str, planilha_diario: str) -> dict:
    """
    Compara valores de impostos entre SPED (C170 por nota) e planilha SAP.

    Chave de cruzamento:
      SPED → C100.NUM_DOC  (C170 linkado via CHV_NFE)
      SAP  → Ref.3 (Linha) (= NUM_DOC da NF)

    Retorna dict com dois grupos de chaves:

    DataFrames (para uso programático):
      'divergencias'       : notas em ambos com DELTA acima da tolerância.
      'so_sped'            : notas no SPED sem lançamento no SAP.
      'so_sap'             : notas no SAP sem correspondência no SPED.
      'lancamentos'        : lançamentos de ajuste no formato de importação SAP.

    JSON equivalente (para APIs, logs ou integração):
      'divergencias_json'  : lista de dicts
      'so_sped_json'       : lista de dicts
      'so_sap_json'        : lista de dicts
      'lancamentos_json'   : lista de dicts
    """
    dfs    = extrai_dados_sped(arquivo_sped)
    df_sap = extrai_dados_planilha_sap(planilha_diario)

    df_sped_agg = _agregar_sped(dfs)
    df_sap_agg  = _agregar_sap(df_sap)

    df = pd.merge(df_sped_agg, df_sap_agg, on="NUM_DOC", how="outer", indicator=True)

    # Notas só em um lado
    df_so_sped = (
        df[df["_merge"] == "left_only"]
        [["NUM_DOC", "CHV_NFE"] + COLS_SPED]
        .reset_index(drop=True)
    )
    sap_cols_presentes = [
        c for c in ["VL_ICMS_SAP", "VL_PIS_SAP", "VL_COFINS_SAP", "VL_ITEM_SAP"]
        if c in df.columns
    ]
    df_so_sap = (
        df[df["_merge"] == "right_only"]
        [["NUM_DOC"] + sap_cols_presentes]
        .reset_index(drop=True)
    )

    # Divergências
    comparacoes = {
        "ICMS":   ("VL_ICMS",   "VL_ICMS_SAP"),
        "PIS":    ("VL_PIS",    "VL_PIS_SAP"),
        "COFINS": ("VL_COFINS", "VL_COFINS_SAP"),
        "ITEM":   ("VL_ITEM",   "VL_ITEM_SAP"),
    }

    df_ambos = df[df["_merge"] == "both"].copy()
    for imposto, (col_sped, col_sap) in comparacoes.items():
        v_sped = df_ambos[col_sped].fillna(0) if col_sped in df_ambos.columns else 0
        v_sap  = df_ambos[col_sap].fillna(0)  if col_sap  in df_ambos.columns else 0
        df_ambos[f"DELTA_{imposto}"] = (v_sped - v_sap).round(2)

    delta_cols = [f"DELTA_{k}" for k in comparacoes]
    sped_cols  = [v[0] for v in comparacoes.values() if v[0] in df_ambos.columns]
    sap_cols   = [v[1] for v in comparacoes.values() if v[1] in df_ambos.columns]

    mask = df_ambos[delta_cols].abs().max(axis=1) > TOLERANCIA
    df_div = (
        df_ambos[mask]
        [["NUM_DOC", "CHV_NFE"] + sped_cols + sap_cols + delta_cols]
        .reset_index(drop=True)
    )

    # Notas OK: presentes nos dois lados e todos os deltas dentro da tolerância
    df_ok = (
        df_ambos[~mask]
        [["NUM_DOC", "CHV_NFE"] + sped_cols + sap_cols]
        .reset_index(drop=True)
    )

    # Lançamentos de ajuste
    df_lanc = gera_lancamentos_ajuste(df_div, df_sap)

    return {
        # DataFrames
        "divergencias":      df_div,
        "ok":                df_ok,
        "so_sped":           df_so_sped,
        "so_sap":            df_so_sap,
        "lancamentos":       df_lanc,
        # JSON equivalente
        "divergencias_json": _df_para_json(df_div),
        "ok_json":           _df_para_json(df_ok),
        "so_sped_json":      _df_para_json(df_so_sped),
        "so_sap_json":       _df_para_json(df_so_sap),
        "lancamentos_json":  _df_para_json(df_lanc),
    }


def gera_lancamentos_ajuste(df_divergencias: pd.DataFrame, df_sap_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Gera lançamentos de ajuste no formato do modelo de importação SAP
    para todas as notas com divergência.

    As contas (código, nome, lado, CC, filial) vêm exclusivamente da
    planilha SAP do cliente — não há contas fixas no código.

    Lógica do ajuste (SPED é considerado correto):
      DELTA = SPED − SAP
      DELTA < 0 → SAP a maior → estorno: inverte o lado de cada lançamento
      DELTA > 0 → SAP a menor → complemento: mantém o lado de cada lançamento
      Valor do lançamento = |DELTA|

    Quando o conjunto de contas mapeadas para um imposto não produz débito E
    crédito (ex: Vendas de Mercadorias só aparece a C; contas a Recuperar só a D),
    a contrapartida é identificada dinamicamente na planilha SAP:
      - Vendas de Mercadorias (saída) → conta do cliente (Cx)
      - Contas a Recuperar (entrada)  → Mercadorias para Revenda - Peças

    Colunas do DataFrame retornado:
      Formato importação : Código da Conta, Descrição da Conta,
                           Débito, Crédito, Descrição, Centro de Custo, Filial
      Rastreabilidade    : NUM_DOC, CHV_NFE, Imposto, DELTA, Sentido
    """
    idx_meta         = _extrair_metadados_contas(df_sap_raw)
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

            # Calcular lado de ajuste de cada conta mapeada
            lados_ajuste = [
                ("C" if c["lado"] == "D" else "D") if delta < 0 else c["lado"]
                for c in contas
            ]

            tem_debito  = any(l == "D" for l in lados_ajuste)
            tem_credito = any(l == "C" for l in lados_ajuste)

            # Se falta um lado, tentar obter a contrapartida dinâmica
            if not tem_debito or not tem_credito:
                cp = idx_contrapartida.get((num_doc, campo))
                if cp:
                    # A contrapartida deve ter o lado OPOSTO ao do campo principal
                    # após aplicar o delta — independente do seu lado original na planilha.
                    # Ex saída : campo=Vendas(C) após ajuste→D; contrapartida→C (cliente)
                    # Ex entrada: campo=ICMS Rec(D) após ajuste→C; contrapartida→D (Mercadorias)
                    lado_campo_principal = lados_ajuste[0] if lados_ajuste else ("C" if delta > 0 else "D")
                    lado_cp_ajuste = "C" if lado_campo_principal == "D" else "D"
                    contas       = list(contas) + [cp]
                    lados_ajuste = lados_ajuste + [lado_cp_ajuste]

            # Emitir uma linha por conta
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
