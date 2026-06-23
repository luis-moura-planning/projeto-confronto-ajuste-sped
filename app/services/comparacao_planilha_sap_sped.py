"""
Reconciliação SAP × SPED (PIS/COFINS)
=====================================

Compara o Diário contábil do SAP com a EFD-Contribuições (SPED PIS/COFINS) e,
para cada documento/conta, classifica o resultado em quatro estados:

    OK          — valores conferem dentro da tolerância
    DIVERGÊNCIA — documento existe nos dois lados, mas com valores diferentes
    SÓ SPED     — escriturado no fisco, ausente no SAP
    SÓ SAP      — lançado no SAP, ausente no fisco (típico de estorno)

Quando o resultado não é OK, o módulo gera os lançamentos contábeis de
acerto (ajuste de divergência, inclusão do que só existe no SPED, estorno do
que só existe no SAP).

A comparação é feita por *domínios*, cada um correspondente a um bloco/natureza
do SPED:

    saída        C100/C170  IND_OPER=1   (notas de venda)            chave NUM_DOC
    entrada      C100/C170  IND_OPER=0   (notas de compra c/ crédito) chave CHV_NFE
    transporte   D100/D101/D105          (CT-e)                       chave CHV_CTE
    energia      C500/C501/C505          (energia/telecom)            chave NUM_DOC
    f100         F100                    (demais operações)           chave COD_CTA
    a100         A100/A170               (serviços, NFS-e)            chave NUM_DOC/valor
    bloco M      M110/M510/M215/M615     (ajustes de apuração)        só-SPED
    f120         F120                    (depreciação de imobilizado) só-SPED + delta

O pipeline de cada domínio é sempre o mesmo:

    agregar_sped → agregar_sap → reconciliar → gerar_lancamentos
"""
import json
import re
from collections import defaultdict
from typing import NamedTuple, Optional

import pandas as pd

from services.extrai_dados_sped import extrai_dados_sped
from services.extrai_dados_planilha_sap import extrai_dados_planilha_sap


# =============================================================================
# 1. CONFIGURAÇÃO DE NEGÓCIO
# =============================================================================
# Tolerância de centavos abaixo da qual duas quantias são consideradas iguais.
TOLERANCIA = 0.05

# Colunas de valor agregadas por bloco do SPED.
COLS_SPED       = ["VL_ITEM", "VL_ICMS", "VL_IPI", "VL_PIS", "VL_COFINS"]
COLS_SPED_D     = ["VL_SERV", "VL_PIS_D", "VL_COFINS_D"]            # transporte
COLS_SPED_F100  = ["VL_PIS", "VL_COFINS"]
COLS_SPED_C500  = ["VL_PIS_C5", "VL_COFINS_C5"]                     # energia
COLS_SPED_A100  = ["VL_PIS", "VL_COFINS"]                           # serviços

# CSTs de PIS/COFINS que NÃO geram crédito → a entrada não é confrontada.
CST_SEM_CREDITO = {"70", "71", "72", "73", "74", "75", "98", "99"}

# COD_SIT de documento que devem ser ignorados (cancelado/denegado) — usado no extrator.
COD_SIT_EXCLUIR = {"02", "08"}

# -- Mapeamento conta SAP (Cta.cont./Nome PN) → campo de valor canônico ----------
MAPA_CONTAS_SAP = {
    "( - ) ICMS":                       "VL_ICMS_SAP",
    "ICMS e Contribuições a Recolher":  "VL_ICMS_SAP",
    "ICMS e Contribuições a Recuperar": "VL_ICMS_SAP",

    "( - ) PIS/PASEP":                  "VL_PIS_SAP",
    "PIS a Recolher":                   "VL_PIS_SAP",
    "PIS a Recuperar":                  "VL_PIS_SAP",

    "( - ) COFINS":                     "VL_COFINS_SAP",
    "COFINS a Recolher":                "VL_COFINS_SAP",
    "COFINS a Recuperar":               "VL_COFINS_SAP",

    "Vendas de Mercadorias":            "VL_ITEM_SAP",

    "Fretes e Carretos":                "VL_SERV_SAP",
    "Frete sobre Compras":              "VL_SERV_SAP",
    "Fretes sobre compras":             "VL_SERV_SAP",
    "Despesas com Fretes":              "VL_SERV_SAP",
}

# Contas de saída (crédito = valor positivo) e de entrada (débito = valor positivo).
CONTAS_SAIDA = {
    "( - ) COFINS", "( - ) ICMS", "( - ) PIS/PASEP",
    "COFINS a Recolher", "ICMS e Contribuições a Recolher", "PIS a Recolher",
    "Vendas de Mercadorias",
}
CONTAS_ENTRADA = {
    "COFINS a Recuperar", "ICMS e Contribuições a Recuperar", "PIS a Recuperar",
    "Fretes e Carretos", "Frete sobre Compras", "Fretes sobre compras",
    "Despesas com Fretes",
}

# Quando várias contas SAP mapeiam para o MESMO campo num documento de saída,
# usa-se a primeira presente nesta ordem de prioridade (evita dupla contagem).
CONTA_CANONICA_SAIDA = {
    "VL_COFINS_SAP": ["COFINS a Recolher",               "( - ) COFINS"],
    "VL_PIS_SAP":    ["PIS a Recolher",                  "( - ) PIS/PASEP"],
    "VL_ICMS_SAP":   ["ICMS e Contribuições a Recolher", "( - ) ICMS"],
    "VL_ITEM_SAP":   ["Vendas de Mercadorias"],
    "VL_SERV_SAP":   ["Fretes e Carretos", "Frete sobre Compras",
                      "Fretes sobre compras", "Despesas com Fretes"],
}

# DELTA_<imposto> da divergência → campo SAP que o origina (usado no ajuste).
# Apenas PIS/COFINS — ICMS/ITEM/SERV não são contribuição e não geram ajuste.
DELTA_PARA_CAMPO = {
    "DELTA_PIS":      "VL_PIS_SAP",
    "DELTA_COFINS":   "VL_COFINS_SAP",
    "DELTA_PIS_D":    "VL_PIS_SAP",
    "DELTA_COFINS_D": "VL_COFINS_SAP",
}

# Contas SAP usadas no crédito de depreciação (F120) — excluídas do F100.
CONTAS_SAP_F120 = frozenset({"5.01.01.06.0003", "5.01.01.06.0004"})

# Contas de crédito SAP cujo "líquido" alimenta o F100.
CONTA_PIS_RECUPERAR    = "PIS a Recuperar"
CONTA_COFINS_RECUPERAR = "COFINS a Recuperar"

# Prefixos do "Nº doc." do SAP que identificam o tipo de documento.
PREFIXOS_TIPO_DOC = frozenset({"DS", "NS", "NE", "LC"})
TIPOS_ESTORNO     = frozenset({"DS", "NS", "NE"})   # documentos fiscais "de verdade"

# -- Plano de contas dos lançamentos gerados -------------------------------------
CC_F100 = {"0": "OBRAS", "1": "ADMIN"}

CONTAS_F100_AVULSO = {
    "0": {  # crédito (entrada)
        "PIS":    {"cod": "1.01.05.01.0003", "nome": "contas pis aproveitamento"},
        "COFINS": {"cod": "1.01.05.01.0004", "nome": "contas Cofins aproveitamento"},
        "lado_fixo": "D", "lado_cta": "C",
    },
    "1": {  # débito (saída)
        "PIS":    {"cod": "2.01.01.04.0002", "nome": "contas pis tem que pagar"},
        "COFINS": {"cod": "2.01.01.04.0003", "nome": "contas cofins tem que pagar"},
        "lado_fixo": "C", "lado_cta": "D",
    },
}

CONTA_CONTRAPARTIDA_M = {"cod": "4.01.01.01.0001", "nome": ""}
CONTAS_M_CREDITO = {
    "M110": {"cod": "1.01.05.01.0003", "nome": "contas pis aproveitamento"},
    "M510": {"cod": "1.01.05.01.0004", "nome": "contas Cofins aproveitamento"},
}
CONTAS_M_DEBITO = {
    "M215": {"cod": "2.01.01.04.0002", "nome": "contas pis tem que pagar"},
    "M615": {"cod": "2.01.01.04.0003", "nome": "contas cofins tem que pagar"},
}
ALIQ_M215 = 1.65 / 100   # PIS sobre base ajustada
ALIQ_M615 = 7.6  / 100   # COFINS sobre base ajustada

DESCR_COD_AJ_BC = {
    "01": "Vendas canceladas de receitas tributadas em períodos anteriores",
    "02": "Devoluções de vendas tributadas em períodos anteriores",
    "21": "ICMS a recolher sobre Operações próprias (PJs com decisão judicial transitada em julgado)",
    "25": "ICMS destacado em documento fiscal complementar, referente a receitas tributadas em períodos anteriores",
    "41": "Outros valores a excluir, vinculados a decisão judicial com trânsito em julgado",
    "42": "Outros valores a excluir, não vinculados a decisão judicial",
}

CONTAS_F120 = {
    "PIS": {
        "dep":  {"cod": "5.01.01.06.0003", "nome": ""},
        "cred": {"cod": "1.01.05.01.0003", "nome": "contas pis aproveitamento"},
    },
    "COFINS": {
        "dep":  {"cod": "5.01.01.06.0004", "nome": ""},
        "cred": {"cod": "1.01.05.01.0004", "nome": "contas Cofins aproveitamento"},
    },
}


# =============================================================================
# 2. PRIMITIVAS NUMÉRICAS E DE TEXTO
# =============================================================================
def _to_float(s) -> float:
    """Converte valores do SPED (vírgula decimal) em float; vazio/erro → 0.0."""
    if not s or str(s).strip() == "":
        return 0.0
    try:
        return float(str(s).replace(",", "."))
    except ValueError:
        return 0.0


def _limpar_valor_sap(v) -> float:
    """Converte 'R$ 1.234,56' (formato SAP) em 1234.56."""
    if pd.isna(v):
        return 0.0
    s = str(v).replace("R$ ", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _df_para_json(df: pd.DataFrame) -> list:
    """DataFrame → lista de dicts JSON-safe."""
    return json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))


# -- Schema único das linhas de lançamento ---------------------------------------
# Todos os geradores produzem linhas com estas colunas. A fábrica abaixo elimina
# a repetição do dicionário de 13 campos que existia em ~10 lugares.
def _linha_lanc(
    cod_conta, nome_conta, lado, valor, descricao,
    *, num_doc="", chv="", cnpj="", cc="", imposto="", delta=None, sentido="",
    **extra,
) -> dict:
    """Cria uma linha de lançamento. `lado` ∈ {'D','C'} define débito/crédito."""
    valor = round(float(valor), 2)
    linha = {
        "Código da Conta":    cod_conta,
        "Descrição da Conta": nome_conta,
        "Débito":             valor if lado == "D" else None,
        "Crédito":            valor if lado == "C" else None,
        "Descrição":          descricao,
        "Centro de Custo":    cc,
        "Filial":             cnpj,
        "NUM_DOC":            num_doc,
        "CHV_NFE":            chv,
        "Imposto":            imposto,
        "DELTA":              delta,
        "Sentido":            sentido,
    }
    linha.update(extra)
    return linha


def _inverter(lado: str) -> str:
    return "C" if lado == "D" else "D"


# =============================================================================
# 3. NORMALIZAÇÃO DO DIÁRIO SAP
# =============================================================================
def _propagar_num_doc(df_sap: pd.DataFrame) -> pd.DataFrame:
    """
    Propaga NUM_DOC e TIPO_DOC linha a linha.

    No Diário, o número do documento (Ref.3) e o tipo (prefixo do Nº doc.: NS/NE/DS/LC)
    aparecem só na primeira linha do lançamento; as demais herdam por preenchimento
    para frente até o próximo cabeçalho (linha com 'Nº seq.').
    """
    df = df_sap.copy()
    df["NUM_DOC"]  = None
    df["TIPO_DOC"] = None
    ref_atual  = None
    tipo_atual = "OUTRO"
    for idx, row in df.iterrows():
        if pd.notna(row["Nº seq."]):                       # novo lançamento
            ref_atual = None
            nrdoc  = str(row.get("Nº doc.", "") or "").strip()
            prefix = nrdoc[:2].upper() if len(nrdoc) >= 2 else ""
            tipo_atual = prefix if prefix in PREFIXOS_TIPO_DOC else "OUTRO"
        if pd.notna(row["Ref.3 (Linha)"]):
            try:
                ref_atual = str(int(float(row["Ref.3 (Linha)"])))
            except (ValueError, TypeError):
                pass
        df.at[idx, "NUM_DOC"]  = ref_atual
        df.at[idx, "TIPO_DOC"] = tipo_atual
    return df


def _valor_sap_correto(row: pd.Series) -> float:
    """Valor de uma linha respeitando a natureza da conta (saída usa crédito; entrada, débito)."""
    conta = str(row.get("Cta.cont./Nome PN", "")).strip()
    deb   = _limpar_valor_sap(row.get("Débito (MC)"))
    cred  = _limpar_valor_sap(row.get("Crédito (MC)"))
    if conta in CONTAS_SAIDA:
        return cred if cred > 0 else deb
    return deb if deb > 0 else cred


# =============================================================================
# 4. AGREGAÇÃO DO SPED (por domínio)
# =============================================================================
def _cnpj_col(df: pd.DataFrame) -> list:
    return ["CNPJ_ESTAB"] if "CNPJ_ESTAB" in df.columns else []


def _agregar_sped(dfs: dict) -> tuple:
    """C100/C170 → (saídas por NUM_DOC, entradas creditáveis por CHV_NFE)."""
    c100 = dfs["C100"].copy()
    c170 = dfs["C170"].copy()

    # VL_ITEM da nota = soma dos itens (C170) por chave.
    c170["_VL_ITEM"] = c170["VL_ITEM"].apply(_to_float)
    vl_item_por_chv = (
        c170.groupby("CHV_NFE")["_VL_ITEM"].sum()
        .reset_index().rename(columns={"_VL_ITEM": "VL_ITEM"})
    )

    for col in ["VL_ICMS", "VL_IPI", "VL_PIS", "VL_COFINS", "VL_MERC"]:
        c100[col] = c100[col].apply(_to_float)
    c100 = c100.merge(vl_item_por_chv, on="CHV_NFE", how="left")
    c100["VL_ITEM"] = c100["VL_ITEM"].fillna(0.0)

    cnpj = _cnpj_col(c100)

    df_saidas = (
        c100[c100["IND_OPER"] == "1"]
        .groupby(["NUM_DOC", "CHV_NFE"] + cnpj)[COLS_SPED].sum().reset_index()
    )

    # Entradas só entram se houver pelo menos um item creditável (CST_PIS válido).
    c170["_tem_credito"] = ~c170["CST_PIS"].isin(CST_SEM_CREDITO)
    chvs_com_credito = set(c170[c170["_tem_credito"]]["CHV_NFE"])
    df_entradas = (
        c100[(c100["IND_OPER"] == "0") & (c100["CHV_NFE"].isin(chvs_com_credito))]
        .groupby(["CHV_NFE", "NUM_DOC"] + cnpj)[COLS_SPED].sum().reset_index()
    )
    return df_saidas, df_entradas


def _agregar_sped_d(dfs: dict) -> pd.DataFrame:
    """D100/D101/D105 → transporte (entrada) por CHV_CTE, com PIS/COFINS de crédito."""
    d100 = dfs.get("D100", pd.DataFrame())
    d101 = dfs.get("D101", pd.DataFrame())
    d105 = dfs.get("D105", pd.DataFrame())
    if d100.empty:
        return pd.DataFrame(columns=["CHV_CTE", "NUM_DOC"] + COLS_SPED_D)

    d100 = d100.copy()
    d100["VL_SERV"] = d100["VL_SERV"].apply(_to_float)

    def _soma_por_cte(df, col_origem, col_destino):
        if df.empty:
            return pd.DataFrame(columns=["CHV_CTE", col_destino])
        df = df.copy()
        df["_v"] = df[col_origem].apply(_to_float)
        return (df.groupby("CHV_CTE")["_v"].sum().reset_index()
                  .rename(columns={"_v": col_destino}))

    pis    = _soma_por_cte(d101, "VL_PIS",    "VL_PIS_D")
    cofins = _soma_por_cte(d105, "VL_COFINS", "VL_COFINS_D")

    cnpj = _cnpj_col(d100)
    df = (d100[d100["IND_OPER"] == "0"]
          .groupby(["CHV_CTE", "NUM_DOC"] + cnpj)["VL_SERV"].sum().reset_index())
    df = df.merge(pis, on="CHV_CTE", how="left").merge(cofins, on="CHV_CTE", how="left")
    df["VL_PIS_D"]    = df["VL_PIS_D"].fillna(0.0)
    df["VL_COFINS_D"] = df["VL_COFINS_D"].fillna(0.0)
    return df


def _agregar_sped_c500(dfs: dict) -> pd.DataFrame:
    """C500/C501/C505 → energia/telecom por NUM_DOC, com PIS/COFINS de crédito."""
    c500 = dfs.get("C500", pd.DataFrame())
    c501 = dfs.get("C501", pd.DataFrame())
    c505 = dfs.get("C505", pd.DataFrame())
    if c500.empty:
        return pd.DataFrame(columns=["NUM_DOC"] + COLS_SPED_C500)

    cols_base = ["NUM_DOC"] + _cnpj_col(c500)
    df = c500[cols_base].drop_duplicates("NUM_DOC").copy()

    def _soma_por_num(df_filho, col_origem, col_destino):
        if df_filho.empty or "NUM_DOC" not in df_filho.columns:
            return pd.DataFrame(columns=["NUM_DOC", col_destino])
        df_filho = df_filho.copy()
        df_filho["_v"] = df_filho[col_origem].apply(_to_float)
        return (df_filho.groupby("NUM_DOC")["_v"].sum().reset_index()
                        .rename(columns={"_v": col_destino}))

    df = df.merge(_soma_por_num(c501, "VL_PIS",    "VL_PIS_C5"),    on="NUM_DOC", how="left")
    df = df.merge(_soma_por_num(c505, "VL_COFINS", "VL_COFINS_C5"), on="NUM_DOC", how="left")
    df["VL_PIS_C5"]    = df["VL_PIS_C5"].fillna(0.0)
    df["VL_COFINS_C5"] = df["VL_COFINS_C5"].fillna(0.0)
    return df


def _agregar_sped_f100(dfs: dict) -> pd.DataFrame:
    """
    F100 → por COD_CTA e IND_OPER.

    IND_OPER=0 (crédito) é agregado por conta; IND_OPER=1 (débito) fica linha a
    linha para preservar a descrição da operação.
    """
    f100 = dfs.get("F100", pd.DataFrame())
    if f100.empty:
        return pd.DataFrame(columns=["COD_CTA", "IND_OPER"] + COLS_SPED_F100)

    f100 = f100.copy()
    f100["VL_PIS"]    = f100["VL_PIS"].apply(_to_float)
    f100["VL_COFINS"] = f100["VL_COFINS"].apply(_to_float)
    cnpj = _cnpj_col(f100)
    grp  = ["COD_CTA", "IND_OPER"]

    oper0 = f100[f100["IND_OPER"].astype(str) == "0"]
    if not oper0.empty:
        agg0 = oper0.groupby(grp)[COLS_SPED_F100].sum().reset_index()
        if cnpj:
            agg0 = agg0.merge(oper0.groupby(grp)["CNPJ_ESTAB"].first().reset_index(),
                              on=grp, how="left")
    else:
        agg0 = pd.DataFrame(columns=grp + COLS_SPED_F100 + cnpj)

    oper1 = f100[f100["IND_OPER"].astype(str) == "1"].copy()
    if not oper1.empty:
        desc = ["DESC_DOC_OPER"] if "DESC_DOC_OPER" in oper1.columns else []
        keep = grp + COLS_SPED_F100 + cnpj + desc
        oper1 = oper1[[c for c in keep if c in oper1.columns]].reset_index(drop=True)
    else:
        oper1 = pd.DataFrame(columns=grp + COLS_SPED_F100 + cnpj)

    return pd.concat([agg0, oper1], ignore_index=True)


def _agregar_sped_a100(dfs: dict) -> tuple:
    """A100 → (saídas serviço por NUM_DOC, entradas serviço creditáveis por CHV_NFSE)."""
    a100 = dfs.get("A100", pd.DataFrame())
    vazio_s = pd.DataFrame(columns=["NUM_DOC"] + COLS_SPED_A100)
    vazio_e = pd.DataFrame(columns=["CHV_NFSE", "NUM_DOC"] + COLS_SPED_A100)
    if a100.empty:
        return vazio_s, vazio_e

    a100 = a100.copy()
    for col in COLS_SPED_A100:
        a100[col] = a100[col].apply(_to_float)
    cnpj = _cnpj_col(a100)

    saidas = a100[a100["IND_OPER"].astype(str) == "1"]
    df_s = (saidas.groupby(["NUM_DOC"] + cnpj)[COLS_SPED_A100].sum().reset_index()
            if not saidas.empty else vazio_s)

    entradas = a100[(a100["IND_OPER"].astype(str) == "0") &
                    ((a100["VL_PIS"] > 0) | (a100["VL_COFINS"] > 0))]
    df_e = (entradas.groupby(["CHV_NFSE", "NUM_DOC"] + cnpj)[COLS_SPED_A100].sum().reset_index()
            if not entradas.empty else vazio_e)
    return df_s, df_e


# =============================================================================
# 5. AGREGAÇÃO DO SAP (por domínio)
# =============================================================================
def _agregar_sap(df_sap: pd.DataFrame, filtro_filial: Optional[str] = None) -> tuple:
    """
    Diário SAP → (saídas, entradas) por NUM_DOC, somente documentos fiscais (NS/NE/DS).

    Saída: valor = crédito − débito; entrada: valor = débito − crédito.
    Quando várias contas mapeiam o mesmo campo, aplica CONTA_CANONICA_SAIDA.
    """
    df = _propagar_num_doc(df_sap)
    df = df[df["TIPO_DOC"].isin(TIPOS_ESTORNO)].copy()
    if filtro_filial and "Nome da filial" in df.columns:
        df = df[df["Nome da filial"].str.contains(filtro_filial, na=False)]
    df = df[df["NUM_DOC"].notna()].copy()
    df["_campo"] = df["Cta.cont./Nome PN"].map(MAPA_CONTAS_SAP)
    df = df[df["_campo"].notna()].copy()

    def _agg(df_linhas: pd.DataFrame, natureza: str) -> pd.DataFrame:
        if df_linhas.empty:
            return pd.DataFrame(columns=["NUM_DOC"])
        rows = []
        for num_doc, grp_doc in df_linhas.groupby("NUM_DOC"):
            row = {"NUM_DOC": num_doc}
            tipos = grp_doc["TIPO_DOC"].dropna() if "TIPO_DOC" in grp_doc.columns else pd.Series([], dtype=str)
            row["TIPO_DOC"] = str(tipos.iloc[0]) if not tipos.empty else "OUTRO"
            for campo, grp_campo in grp_doc.groupby("_campo"):
                if campo in CONTA_CANONICA_SAIDA:
                    presentes = set(grp_campo["Cta.cont./Nome PN"].unique())
                    for conta_pref in CONTA_CANONICA_SAIDA[campo]:
                        if conta_pref in presentes:
                            grp_campo = grp_campo[grp_campo["Cta.cont./Nome PN"] == conta_pref]
                            break
                deb  = grp_campo["Débito (MC)"].apply(_limpar_valor_sap).sum()
                cred = grp_campo["Crédito (MC)"].apply(_limpar_valor_sap).sum()
                row[campo] = round(cred - deb, 2) if natureza == "saida" else round(deb - cred, 2)
            rows.append(row)
        df_res = pd.DataFrame(rows)
        num_cols = [c for c in df_res.columns if c not in ("NUM_DOC", "TIPO_DOC")]
        df_res[num_cols] = df_res[num_cols].fillna(0)
        return df_res

    saidas   = df[df["Cta.cont./Nome PN"].isin(CONTAS_SAIDA)]
    entradas = df[df["Cta.cont./Nome PN"].isin(CONTAS_ENTRADA)]
    return _agg(saidas, "saida"), _agg(entradas, "entrada")


def _net_credito_recuperar(df_src: pd.DataFrame, conta_nome: str, campo: str,
                           nome_lookup: dict) -> pd.DataFrame:
    """Soma líquida (déb−créd) das contas de crédito a recuperar, por contrapartida (COD_CTA)."""
    linhas = df_src[df_src["Cta.cont./Nome PN"] == conta_nome]
    if linhas.empty:
        return pd.DataFrame(columns=["COD_CTA", campo])
    rows = []
    for contra, grp in linhas.groupby("Conta de contrapartida"):
        contra = str(contra).strip()
        if not contra[:1].isdigit() or contra in CONTAS_SAP_F120:
            continue
        net = round(grp["Débito (MC)"].apply(_limpar_valor_sap).sum()
                    - grp["Crédito (MC)"].apply(_limpar_valor_sap).sum(), 2)
        if net > 0:
            rows.append({"COD_CTA": contra, campo: net})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["COD_CTA", campo])


def _agregar_sap_f100(df_contas: pd.DataFrame) -> tuple:
    """
    Crédito SAP (PIS/COFINS a Recuperar) líquido por contrapartida → confronto com F100.

    Retorna (df_all, lc_only_contas):
      df_all          — totais considerando todos os tipos de documento.
      lc_only_contas  — COD_CTAs que só têm lançamento avulso (sem documento fiscal);
                        nesses casos a divergência vira só advertência, sem lançamento.
    """
    excluir = {CONTA_PIS_RECUPERAR, CONTA_COFINS_RECUPERAR}
    nome_lookup = {
        str(r.get("Cta.contáb./cód.PN", "")).strip(): str(r.get("Cta.cont./Nome PN", "")).strip()
        for _, r in df_contas.iterrows()
        if str(r.get("Cta.contáb./cód.PN", "")).strip()
        and str(r.get("Cta.cont./Nome PN", "")).strip() not in excluir
    }

    df_prop   = _propagar_num_doc(df_contas)
    df_fiscal = df_prop[df_prop["TIPO_DOC"].isin(TIPOS_ESTORNO)]

    def _merge(df_src):
        pis = _net_credito_recuperar(df_src, CONTA_PIS_RECUPERAR,    "VL_PIS_SAP",    nome_lookup)
        cof = _net_credito_recuperar(df_src, CONTA_COFINS_RECUPERAR, "VL_COFINS_SAP", nome_lookup)
        if pis.empty and cof.empty:
            return pd.DataFrame(columns=["COD_CTA", "VL_PIS_SAP", "VL_COFINS_SAP"])
        df = pis.merge(cof, on="COD_CTA", how="outer")
        df["VL_PIS_SAP"]    = df["VL_PIS_SAP"].fillna(0.0)
        df["VL_COFINS_SAP"] = df["VL_COFINS_SAP"].fillna(0.0)
        return df

    df_all = _merge(df_prop)
    if df_all.empty:
        return pd.DataFrame(columns=["COD_CTA", "NOME_CONTA", "VL_PIS_SAP", "VL_COFINS_SAP"]), frozenset()
    df_all.insert(1, "NOME_CONTA", df_all["COD_CTA"].map(nome_lookup).fillna(""))

    fiscal = _merge(df_fiscal)
    fiscal_contas  = frozenset(fiscal["COD_CTA"]) if not fiscal.empty else frozenset()
    lc_only_contas = frozenset(df_all["COD_CTA"]) - fiscal_contas
    return df_all, lc_only_contas


def _agregar_sap_f120(df_contas: pd.DataFrame) -> dict:
    """PIS/COFINS creditados nas contas de depreciação (CONTAS_SAP_F120)."""
    pis = cof = 0.0
    for conta_nome in (CONTA_PIS_RECUPERAR, CONTA_COFINS_RECUPERAR):
        linhas = df_contas[df_contas["Cta.cont./Nome PN"] == conta_nome]
        for contra, grp in linhas.groupby("Conta de contrapartida"):
            if str(contra).strip() not in CONTAS_SAP_F120:
                continue
            net = round(grp["Débito (MC)"].apply(_limpar_valor_sap).sum()
                        - grp["Crédito (MC)"].apply(_limpar_valor_sap).sum(), 2)
            if net <= 0:
                continue
            if "PIS" in conta_nome:
                pis += net
            else:
                cof += net
    return {"VL_PIS_SAP": round(pis, 2), "VL_COFINS_SAP": round(cof, 2)}


# =============================================================================
# 6. METADADOS DE CONTA (para montar os lançamentos de ajuste)
# =============================================================================
def _meta_linha(r) -> dict:
    return {
        "cod_conta":  str(r["Cta.contáb./cód.PN"]).strip(),
        "nome_conta": str(r["Cta.cont./Nome PN"]).strip(),
        "cc":     str(r["Centro de Custo"]) if pd.notna(r["Centro de Custo"]) else "",
        "filial": str(r["Nome da filial"])  if pd.notna(r.get("Nome da filial")) else "",
        "obs":    str(r["Observações"])     if pd.notna(r["Observações"]) else "",
    }


def _extrair_metadados_contas(df_sap: pd.DataFrame) -> dict:
    """(NUM_DOC, campo) → lista de contas SAP envolvidas, com lado (D/C) e metadados."""
    df = _propagar_num_doc(df_sap)
    if "Nome da filial" not in df.columns:
        df["Nome da filial"] = ""

    vistos, idx = set(), defaultdict(list)
    for _, r in df[df["NUM_DOC"].notna()].iterrows():
        conta = str(r["Cta.cont./Nome PN"]).strip()
        if conta not in MAPA_CONTAS_SAP:
            continue
        campo   = MAPA_CONTAS_SAP[conta]
        num_doc = r["NUM_DOC"]
        cod     = str(r["Cta.contáb./cód.PN"]).strip()
        lado    = "D" if _limpar_valor_sap(r["Débito (MC)"]) > 0 else "C"
        chave   = (num_doc, campo, cod, lado)
        if chave in vistos:
            continue
        vistos.add(chave)
        idx[(num_doc, campo)].append({**_meta_linha(r), "lado": lado})
    return idx


def _extrair_contrapartidas(df_sap: pd.DataFrame) -> dict:
    """
    (NUM_DOC, campo) → conta de contrapartida, usada para equilibrar o ajuste
    quando o débito e o crédito não estão ambos em contas mapeadas.
    """
    df = _propagar_num_doc(df_sap)
    if "Nome da filial" not in df.columns:
        df["Nome da filial"] = ""

    CAMPOS_SAIDA   = {"VL_ITEM_SAP"}
    CAMPOS_ENTRADA = {"VL_ICMS_SAP", "VL_PIS_SAP", "VL_COFINS_SAP"}
    EXCLUIR_SAIDA  = {"Mercadorias para Revenda - Peças", "Custo dos Produtos Vendidos"}
    resultado = {}

    for num_doc, grupo in df[df["NUM_DOC"].notna()].groupby("NUM_DOC"):
        campos_presentes = {
            MAPA_CONTAS_SAP[str(r["Cta.cont./Nome PN"]).strip()]
            for _, r in grupo.iterrows()
            if str(r["Cta.cont./Nome PN"]).strip() in MAPA_CONTAS_SAP
        }
        for campo in campos_presentes:
            if campo in CAMPOS_SAIDA:
                cand = grupo[
                    ~grupo["Cta.cont./Nome PN"].isin(MAPA_CONTAS_SAP) &
                    ~grupo["Cta.cont./Nome PN"].isin(EXCLUIR_SAIDA) &
                    grupo["Débito (MC)"].apply(lambda v: _limpar_valor_sap(v) > 0)
                ]
                if cand.empty:
                    continue
                resultado[(num_doc, campo)] = {**_meta_linha(cand.iloc[0]), "lado": "D"}
            elif campo in CAMPOS_ENTRADA:
                merc = grupo[grupo["Cta.cont./Nome PN"].astype(str).str.strip()
                             == "Mercadorias para Revenda - Peças"]
                if merc.empty:
                    continue
                r = merc.iloc[0]
                lado = "D" if _limpar_valor_sap(r["Débito (MC)"]) > 0 else "C"
                resultado[(num_doc, campo)] = {**_meta_linha(r), "lado": lado}
    return resultado


# =============================================================================
# 7. MOTOR DE RECONCILIAÇÃO
# =============================================================================
class Reconciliacao(NamedTuple):
    """Resultado da reconciliação de um domínio."""
    divergencias: pd.DataFrame
    ok:           pd.DataFrame
    so_sped:      pd.DataFrame
    so_sap:       pd.DataFrame


def reconciliar(df_sped, df_sap, comparacoes: dict, chave="NUM_DOC",
                extra_cols=None) -> Reconciliacao:
    """
    Confronta SPED × SAP por `chave` e classifica em divergência/ok/só-SPED/só-SAP.

    `comparacoes` = {imposto: (col_sped, col_sap)} define os pares confrontados;
    a diferença (sped − sap) vira a coluna DELTA_<imposto>.
    """
    df = pd.merge(df_sped, df_sap, on=chave, how="outer", indicator=True)

    if "NUM_DOC_x" in df.columns:                       # NUM_DOC presente nos dois lados
        df["NUM_DOC"] = df["NUM_DOC_x"].fillna(df["NUM_DOC_y"])
        df.drop(columns=["NUM_DOC_x", "NUM_DOC_y"], inplace=True)

    id_cols  = [chave] + (["NUM_DOC"] if chave != "NUM_DOC" and "NUM_DOC" in df.columns else [])
    chv_cols = [c for c in ["CHV_NFE", "CHV_CTE"] if c in df.columns and c != chave]
    cnpj_col = ["CNPJ_ESTAB"] if "CNPJ_ESTAB" in df.columns else []
    sap_cols = [c for c in df_sap.columns if c != chave and c in df.columns and c not in id_cols]
    extra    = [c for c in (extra_cols or []) if c in df.columns and c not in id_cols]

    cols_sped_val = [c for c in (COLS_SPED + COLS_SPED_D + COLS_SPED_C500) if c in df.columns]

    so_sped = (df[df["_merge"] == "left_only"]
               [id_cols + chv_cols + cnpj_col + cols_sped_val + extra].reset_index(drop=True))
    so_sap  = (df[df["_merge"] == "right_only"]
               [id_cols + sap_cols].reset_index(drop=True))

    ambos = df[df["_merge"] == "both"].copy()
    delta_cols = []
    for imposto, (col_sped, col_sap) in comparacoes.items():
        v_sped = ambos[col_sped].fillna(0) if col_sped in ambos.columns else 0
        v_sap  = ambos[col_sap].fillna(0)  if col_sap  in ambos.columns else 0
        dc = f"DELTA_{imposto}"
        ambos[dc] = (v_sped - v_sap).round(2)
        delta_cols.append(dc)

    sped_cols = [v[0] for v in comparacoes.values() if v[0] in ambos.columns]
    sapc_cols = [v[1] for v in comparacoes.values() if v[1] in ambos.columns]
    diverge   = ambos[delta_cols].abs().max(axis=1) > TOLERANCIA

    divergencias = (ambos[diverge]
                    [id_cols + chv_cols + cnpj_col + sped_cols + sapc_cols + delta_cols + extra]
                    .reset_index(drop=True))
    ok = (ambos[~diverge]
          [id_cols + chv_cols + cnpj_col + sped_cols + sapc_cols + extra].reset_index(drop=True))
    return Reconciliacao(divergencias, ok, so_sped, so_sap)


def reconciliar_a100_por_valor(so_sped, so_sap,
                               col_pis_sped="VL_PIS", col_cof_sped="VL_COFINS",
                               col_pis_sap="VL_PIS_SAP", col_cof_sap="VL_COFINS_SAP") -> tuple:
    """
    Casa A100 por (CNPJ, PIS, COFINS) quando não há chave de documento comum.

    Só casa chaves cuja contagem é idêntica nos dois lados (lida com duplicatas
    simétricas sem produto cartesiano). Retorna (ok, sobra_sped, sobra_sap).
    """
    if so_sped.empty or so_sap.empty:
        return pd.DataFrame(), so_sped.reset_index(drop=True), so_sap.reset_index(drop=True)

    sped = so_sped.copy().reset_index(drop=True)
    sap  = so_sap.copy().reset_index(drop=True)
    usa_cnpj  = "CNPJ_ESTAB" in sped.columns and "CNPJ_ESTAB" in sap.columns
    cnpj_sped = sped["CNPJ_ESTAB"].fillna("") if usa_cnpj else pd.Series([""] * len(sped))
    cnpj_sap  = sap["CNPJ_ESTAB"].fillna("")  if usa_cnpj else pd.Series([""] * len(sap))

    sped["_vk"] = (cnpj_sped + "|" + sped[col_pis_sped].fillna(0).round(2).astype(str)
                   + "|" + sped[col_cof_sped].fillna(0).round(2).astype(str))
    sap["_vk"]  = (cnpj_sap + "|" + sap[col_pis_sap].fillna(0).round(2).astype(str)
                   + "|" + sap[col_cof_sap].fillna(0).round(2).astype(str))

    sped_cnt, sap_cnt = sped["_vk"].value_counts(), sap["_vk"].value_counts()
    common = {k for k in set(sped_cnt.index) & set(sap_cnt.index) if sped_cnt[k] == sap_cnt[k]}
    if not common:
        return pd.DataFrame(), so_sped.reset_index(drop=True), so_sap.reset_index(drop=True)

    sped_hit = sped[sped["_vk"].isin(common)].copy()
    sap_hit  = sap[sap["_vk"].isin(common)].copy()
    # casa posicionalmente dentro de cada grupo de chave (evita cartesiano)
    sped_hit["_full"] = sped_hit["_vk"] + "|" + sped_hit.groupby("_vk").cumcount().astype(str)
    sap_hit["_full"]  = sap_hit["_vk"]  + "|" + sap_hit.groupby("_vk").cumcount().astype(str)

    sap_extra = [c for c in sap_hit.columns
                 if c not in ("_vk", "_full") and c not in sped_hit.columns]
    ok = (sped_hit.merge(sap_hit[["_full"] + sap_extra], on="_full", how="inner")
                  .drop(columns=["_vk", "_full"]).reset_index(drop=True))
    ok["_a100"] = True
    sobra_sped = sped[~sped["_vk"].isin(common)].drop(columns=["_vk"]).reset_index(drop=True)
    sobra_sap  = sap[~sap["_vk"].isin(common)].drop(columns=["_vk"]).reset_index(drop=True)
    return ok, sobra_sped, sobra_sap


# =============================================================================
# 8. GERAÇÃO DE LANÇAMENTOS
# =============================================================================
def _df(linhas: list) -> pd.DataFrame:
    return pd.DataFrame(linhas) if linhas else pd.DataFrame()


def gera_lancamentos_ajuste(df_divergencias: pd.DataFrame, df_sap_raw: pd.DataFrame) -> pd.DataFrame:
    """Ajusta divergências de valor (NFe/transporte/energia/A100) pelo DELTA."""
    idx_meta = _extrair_metadados_contas(df_sap_raw)
    idx_cp   = _extrair_contrapartidas(df_sap_raw)
    linhas = []

    for _, row in df_divergencias.iterrows():
        num_doc = str(row["NUM_DOC"])
        chv     = row.get("CHV_NFE", "")
        cnpj    = str(row.get("CNPJ_ESTAB", "") or "")

        for delta_col, campo in DELTA_PARA_CAMPO.items():
            if delta_col not in row.index or pd.isna(row[delta_col]):
                continue
            delta = round(float(row[delta_col]), 2)
            if abs(delta) <= TOLERANCIA:
                continue

            contas = idx_meta.get((num_doc, campo), [])
            if not contas:
                continue

            valor   = round(abs(delta), 2)
            sentido = "SAP a maior (estorno)" if delta < 0 else "SAP a menor (complemento)"
            # delta<0 inverte o lado natural da conta (estorno); delta>0 mantém (complemento)
            lados = [_inverter(c["lado"]) if delta < 0 else c["lado"] for c in contas]

            # Equilíbrio: se não há débito E crédito, busca contrapartida.
            if not (any(l == "D" for l in lados) and any(l == "C" for l in lados)):
                cp = idx_cp.get((num_doc, campo))
                if not cp:
                    continue  # lançamento ficaria desbalanceado → pula
                lado_principal = lados[0] if lados else ("C" if delta > 0 else "D")
                contas = list(contas) + [cp]
                lados  = lados + [_inverter(lado_principal)]

            for c, lado in zip(contas, lados):
                desc = f"NF {num_doc} - {c['obs']}" if c["obs"] else f"NF {num_doc}"
                linhas.append(_linha_lanc(
                    c["cod_conta"], c["nome_conta"], lado, valor, desc,
                    num_doc=num_doc, chv=chv, cnpj=cnpj or c["filial"], cc=c["cc"],
                    imposto=delta_col.replace("DELTA_", ""), delta=delta, sentido=sentido,
                ))
    return _df(linhas)


def gera_lancamentos_ajuste_f100(df_divergencias_f100: pd.DataFrame,
                                 lc_contas: frozenset = frozenset()) -> pd.DataFrame:
    """Ajusta divergências do F100 (PIS/COFINS) por conta contábil."""
    if df_divergencias_f100.empty:
        return pd.DataFrame()
    DELTA_F100 = {"DELTA_PIS": "PIS", "DELTA_COFINS": "COFINS"}
    linhas = []
    for _, row in df_divergencias_f100.iterrows():
        cod_cta = str(row["COD_CTA"])
        if cod_cta in lc_contas:                       # só avulso → só advertência
            continue
        nome_cta = str(row.get("NOME_CONTA", ""))
        cnpj     = str(row.get("CNPJ_ESTAB", "") or "")
        ind_oper = str(row.get("IND_OPER", "0"))
        cc       = CC_F100.get(ind_oper, "OBRAS")
        regra    = CONTAS_F100_AVULSO.get(ind_oper, CONTAS_F100_AVULSO["0"])
        desc     = "F100" + (f" - {nome_cta}" if nome_cta else "")

        for delta_col, imposto in DELTA_F100.items():
            if delta_col not in row.index:
                continue
            delta = round(float(row[delta_col]), 2)
            if abs(delta) <= TOLERANCIA:
                continue
            info    = regra[imposto]
            valor   = round(abs(delta), 2)
            sentido = "SAP a maior (estorno)" if delta < 0 else "SAP a menor (complemento)"
            lado_fixo = regra["lado_fixo"] if delta > 0 else _inverter(regra["lado_fixo"])
            lado_cta  = regra["lado_cta"]  if delta > 0 else _inverter(regra["lado_cta"])
            for cod_c, nome_c, lado in [(info["cod"], info["nome"], lado_fixo),
                                        (cod_cta,     nome_cta,     lado_cta)]:
                linhas.append(_linha_lanc(
                    cod_c, nome_c, lado, valor, desc, cnpj=cnpj, cc=cc,
                    imposto=imposto, delta=delta, sentido=sentido,
                    COD_CTA=cod_cta, NOME_CONTA=nome_cta,
                ))
    return _df(linhas)


def gera_lancamentos_so_sped(df_sap_raw, so_sped_entrada, so_sped_transporte,
                             so_sped_f100, so_sped_c500) -> pd.DataFrame:
    """Inclui no SAP o crédito de PIS/COFINS que só existe no SPED."""
    cod_pis = cod_cofins = ""
    for _, r in df_sap_raw.iterrows():
        nome = str(r.get("Cta.cont./Nome PN", "")).strip()
        cod  = str(r.get("Cta.contáb./cód.PN", "")).strip()
        if nome == CONTA_PIS_RECUPERAR and not cod_pis:
            cod_pis = cod
        if nome == CONTA_COFINS_RECUPERAR and not cod_cofins:
            cod_cofins = cod
        if cod_pis and cod_cofins:
            break

    linhas = []

    def _credito(vl_pis, vl_cofins, descricao, num_doc="", chv="", cnpj="", cc=""):
        for cod, nome, imposto, valor in [
            (cod_pis,    CONTA_PIS_RECUPERAR,    "PIS",    _to_float(vl_pis)),
            (cod_cofins, CONTA_COFINS_RECUPERAR, "COFINS", _to_float(vl_cofins)),
        ]:
            if abs(valor) > TOLERANCIA:
                linhas.append(_linha_lanc(
                    cod, nome, "D", round(valor, 2), descricao,
                    num_doc=num_doc, chv=chv, cnpj=cnpj, cc=cc,
                    imposto=imposto, sentido="Só SPED",
                ))

    for _, row in so_sped_entrada.iterrows():
        num, chv = str(row.get("NUM_DOC", "")), str(row.get("CHV_NFE", ""))
        cnpj = str(row.get("CNPJ_ESTAB", "") or "")
        _credito(row.get("VL_PIS", 0), row.get("VL_COFINS", 0),
                 f"NF {num}" if num else f"CHV {chv[:20]}", num, chv, cnpj)

    for _, row in so_sped_transporte.iterrows():
        num, chv = str(row.get("NUM_DOC", "")), str(row.get("CHV_CTE", ""))
        cnpj = str(row.get("CNPJ_ESTAB", "") or "")
        _credito(row.get("VL_PIS_D", 0), row.get("VL_COFINS_D", 0),
                 f"CT-e {num}" if num else f"CTE {chv[:20]}", num, chv, cnpj)

    for _, row in so_sped_f100.iterrows():
        cod_cta  = str(row.get("COD_CTA", ""))
        nome_cta = str(row.get("NOME_CONTA", ""))
        cnpj     = str(row.get("CNPJ_ESTAB", "") or "")
        ind_oper = str(row.get("IND_OPER", "0"))
        cc       = CC_F100.get(ind_oper, "OBRAS")
        regra    = CONTAS_F100_AVULSO.get(ind_oper, CONTAS_F100_AVULSO["0"])
        desc     = "F100" + (f" - {nome_cta}" if nome_cta else "")
        for imposto, col in [("PIS", "VL_PIS"), ("COFINS", "VL_COFINS")]:
            valor = _to_float(row.get(col, 0))
            if abs(valor) <= TOLERANCIA:
                continue
            info = regra[imposto]
            for cod_c, nome_c, lado in [(info["cod"], info["nome"], regra["lado_fixo"]),
                                        (cod_cta,     nome_cta,     regra["lado_cta"])]:
                linhas.append(_linha_lanc(
                    cod_c, nome_c, lado, round(valor, 2), desc, cc=cc, cnpj=cnpj,
                    imposto=imposto, sentido="Só SPED",
                ))

    for _, row in so_sped_c500.iterrows():
        num  = str(row.get("NUM_DOC", ""))
        cnpj = str(row.get("CNPJ_ESTAB", "") or "")
        _credito(row.get("VL_PIS_C5", 0), row.get("VL_COFINS_C5", 0),
                 f"Energia/Telecom {num}" if num else "C500", num, cnpj=cnpj)

    return _df(linhas)


def _cnpj_matriz(dfs: dict) -> str:
    df0 = dfs.get("0000", pd.DataFrame())
    return str(df0["CNPJ"].iloc[0]).strip() if not df0.empty and "CNPJ" in df0.columns else ""


def gera_lancamentos_m110_m510(dfs: dict) -> pd.DataFrame:
    """Ajustes de crédito de apuração (M110=PIS, M510=COFINS)."""
    cnpj = _cnpj_matriz(dfs)
    linhas = []
    for reg, imposto in [("M110", "PIS"), ("M510", "COFINS")]:
        df_m = dfs.get(reg, pd.DataFrame())
        if df_m.empty:
            continue
        info = CONTAS_M_CREDITO[reg]
        for _, row in df_m.iterrows():
            vl_aj = _to_float(row.get("VL_AJ", 0))
            if abs(vl_aj) <= TOLERANCIA:
                continue
            ind_aj   = str(row.get("IND_AJ", "0"))
            cod_aj   = str(row.get("COD_AJ", ""))
            descr_aj = str(row.get("DESCR_AJ", ""))
            desc     = f"{reg} {cod_aj}" + (f" - {descr_aj}" if descr_aj else "")
            valor    = round(abs(vl_aj), 2)
            lado_cred, lado_contra = ("C", "D") if ind_aj == "0" else ("D", "C")
            for cod_c, nome_c, lado in [
                (info["cod"], info["nome"], lado_cred),
                (CONTA_CONTRAPARTIDA_M["cod"], CONTA_CONTRAPARTIDA_M["nome"], lado_contra),
            ]:
                linhas.append(_linha_lanc(
                    cod_c, nome_c, lado, valor, desc, num_doc=str(row.get("NUM_DOC", "")),
                    cnpj=cnpj, cc="OBRAS", imposto=imposto, sentido="Só SPED",
                ))
    return _df(linhas)


def gera_lancamentos_m215_m615(dfs: dict) -> pd.DataFrame:
    """Ajustes de base de cálculo (M215=PIS, M615=COFINS) → imposto = base × alíquota."""
    cnpj = _cnpj_matriz(dfs)
    linhas = []
    for reg, imposto, aliq in [("M215", "PIS", ALIQ_M215), ("M615", "COFINS", ALIQ_M615)]:
        df_m = dfs.get(reg, pd.DataFrame())
        if df_m.empty:
            continue
        info = CONTAS_M_DEBITO[reg]
        for _, row in df_m.iterrows():
            ind_aj = str(row.get("IND_AJ_BC", "0"))
            cod_aj = str(row.get("COD_AJ_BC", "")).strip()
            if ind_aj == "0" and not cod_aj:              # ajuste de redução exige código
                continue
            valor = round(abs(_to_float(row.get("VL_AJ_BC", 0))) * aliq, 2)
            if valor <= TOLERANCIA:
                continue
            descr = DESCR_COD_AJ_BC.get(cod_aj, str(row.get("DESCR_AJ_BC", "") or ""))
            desc  = f"{reg} {cod_aj}" + (f" - {descr}" if descr else "")
            lado_conta, lado_contra = ("D", "C") if ind_aj == "0" else ("C", "D")
            for cod_c, nome_c, lado in [
                (info["cod"], info["nome"], lado_conta),
                (CONTA_CONTRAPARTIDA_M["cod"], CONTA_CONTRAPARTIDA_M["nome"], lado_contra),
            ]:
                linhas.append(_linha_lanc(
                    cod_c, nome_c, lado, valor, desc, num_doc=str(row.get("NUM_DOC", "")),
                    cnpj=cnpj, cc="OBRAS", imposto=imposto, sentido="Só SPED",
                ))
    return _df(linhas)


def gera_lancamentos_f120(dfs: dict) -> pd.DataFrame:
    """Crédito de depreciação de imobilizado (F120), linha a linha."""
    f120 = dfs.get("F120", pd.DataFrame())
    if f120.empty:
        return pd.DataFrame()
    linhas = []
    for _, row in f120.iterrows():
        ind  = str(row.get("IND_ORIG_CRED", "0"))
        cnpj = str(row.get("CNPJ_ESTAB", "") or "")
        desc = f"F120 {row.get('IDENT_BEM_IMOB', '')}" + (
            f" - {row.get('DESC_BEM_IMOB', '')}" if row.get("DESC_BEM_IMOB", "") else "")
        lado_dep, lado_cred = ("D", "C") if ind == "0" else ("C", "D")
        for imposto, col in [("PIS", "VL_PIS"), ("COFINS", "VL_COFINS")]:
            valor = _to_float(row.get(col, 0))
            if abs(valor) <= TOLERANCIA:
                continue
            contas = CONTAS_F120[imposto]
            valor_r = round(abs(valor), 2)
            for info, lado in [(contas["dep"], lado_dep), (contas["cred"], lado_cred)]:
                linhas.append(_linha_lanc(
                    info["cod"], info["nome"], lado, valor_r, desc, cnpj=cnpj, cc="OBRAS",
                    imposto=imposto, sentido="Só SPED",
                ))
    return _df(linhas)


def gera_lancamentos_f120_delta(dfs: dict, sap_f120: dict) -> pd.DataFrame:
    """Delta entre F120 total (SPED) e depreciação SAP (5.01.01.06.x)."""
    f120 = dfs.get("F120", pd.DataFrame())
    if f120.empty:
        return pd.DataFrame()
    cnpj = _cnpj_matriz(dfs)
    deltas = {
        "PIS":    round(round(f120["VL_PIS"].apply(_to_float).sum(), 2)    - sap_f120.get("VL_PIS_SAP", 0.0), 2),
        "COFINS": round(round(f120["VL_COFINS"].apply(_to_float).sum(), 2) - sap_f120.get("VL_COFINS_SAP", 0.0), 2),
    }
    linhas = []
    for imposto, delta in deltas.items():
        if abs(delta) <= TOLERANCIA:
            continue
        contas  = CONTAS_F120[imposto]
        valor   = round(abs(delta), 2)
        sentido = "SAP a menor (complemento)" if delta > 0 else "SAP a maior (estorno)"
        lado_dep, lado_cred = ("D", "C") if delta > 0 else ("C", "D")
        for info, lado in [(contas["dep"], lado_dep), (contas["cred"], lado_cred)]:
            linhas.append(_linha_lanc(
                info["cod"], info["nome"], lado, valor, f"F120 {imposto} - ajuste depreciacao",
                cnpj=cnpj, cc="OBRAS", imposto=imposto, delta=delta, sentido=sentido,
            ))
    return _df(linhas)


def gera_lancamentos_estorno_so_sap(so_sap_df: pd.DataFrame, df_sap_raw: pd.DataFrame) -> pd.DataFrame:
    """Estorna documentos fiscais que existem no SAP mas não no SPED."""
    if so_sap_df.empty or "TIPO_DOC" not in so_sap_df.columns:
        return pd.DataFrame()
    df_estorno = so_sap_df[so_sap_df["TIPO_DOC"].isin(TIPOS_ESTORNO)]
    if df_estorno.empty:
        return pd.DataFrame()

    num_docs = set(df_estorno["NUM_DOC"].dropna().astype(str))
    det = _propagar_num_doc(df_sap_raw)
    det = det[det["NUM_DOC"].isin(num_docs) & det["NUM_DOC"].notna()
              & det["Cta.cont./Nome PN"].notna() & det["TIPO_DOC"].isin(TIPOS_ESTORNO)].copy()
    if det.empty:
        return pd.DataFrame()
    det["_deb"]  = det["Débito (MC)"].apply(_limpar_valor_sap)
    det["_cred"] = det["Crédito (MC)"].apply(_limpar_valor_sap)

    linhas = []
    for (num_doc, conta), grp in det[det["Cta.cont./Nome PN"].isin(MAPA_CONTAS_SAP)] \
            .groupby(["NUM_DOC", "Cta.cont./Nome PN"]):
        net_deb = round(grp["_deb"].sum() - grp["_cred"].sum(), 2)
        if abs(net_deb) <= TOLERANCIA:
            continue
        cod    = str(grp["Cta.contáb./cód.PN"].iloc[0]).strip()
        tipo   = str(grp["TIPO_DOC"].iloc[0]).strip()
        filial = str(grp["Nome da filial"].iloc[0]) if "Nome da filial" in grp.columns \
                 and pd.notna(grp["Nome da filial"].iloc[0]) else ""
        cc     = str(grp["Centro de Custo"].iloc[0]) if "Centro de Custo" in grp.columns \
                 and pd.notna(grp["Centro de Custo"].iloc[0]) else ""
        imposto = MAPA_CONTAS_SAP.get(str(conta), "").replace("VL_", "").replace("_SAP", "")
        # estorno = lado oposto ao líquido: net>0 (era débito) → credita
        lado = "C" if net_deb > 0 else "D"
        linhas.append(_linha_lanc(
            cod, conta, lado, abs(net_deb), f"Estorno {tipo} NF {num_doc}",
            num_doc=num_doc, cc=cc, cnpj=filial, imposto=imposto, sentido="Só SAP - Estorno",
        ))
    if not linhas:
        return pd.DataFrame()

    # Equilibra documentos que ficaram desbalanceados (ex.: NE sem contrapartida mapeada).
    idx_cp = _extrair_contrapartidas(df_sap_raw)
    saldo, ref = defaultdict(float), {}
    for l in linhas:
        nd = l["NUM_DOC"]
        saldo[nd] += (float(l["Débito"]) if l["Débito"] is not None else 0.0) \
                     - (float(l["Crédito"]) if l["Crédito"] is not None else 0.0)
        ref[nd] = l
    extras = []
    for nd, delta in saldo.items():
        if abs(delta) <= TOLERANCIA:
            continue
        cp = next((idx_cp.get((nd, c)) for c in ("VL_PIS_SAP", "VL_COFINS_SAP", "VL_ICMS_SAP")
                   if idx_cp.get((nd, c))), None)
        if not cp:
            continue
        r = ref[nd]
        extras.append(_linha_lanc(
            cp["cod_conta"], cp["nome_conta"], "D" if delta < 0 else "C", abs(delta),
            r["Descrição"], num_doc=nd, cc=cp.get("cc") or r["Centro de Custo"],
            cnpj=cp.get("filial") or r["Filial"], sentido="Só SAP - Estorno",
        ))
    return pd.DataFrame(linhas + extras)


# =============================================================================
# 9. NORMALIZAÇÃO PARA EXIBIÇÃO (blocos M e F120 — só-SPED)
# =============================================================================
def _normaliza_m_para_comparacao(dfs: dict) -> list:
    cnpj = _cnpj_matriz(dfs)
    linhas = []
    for reg in ("M110", "M510"):
        df_m = dfs.get(reg, pd.DataFrame())
        for _, row in df_m.iterrows():
            vl_aj = _to_float(row.get("VL_AJ", 0))
            if abs(vl_aj) <= TOLERANCIA:
                continue
            linhas.append({
                "REG": reg, "NUM_DOC": str(row.get("NUM_DOC", "") or ""),
                "VL_PIS":    round(abs(vl_aj), 2) if reg == "M110" else 0.0,
                "VL_COFINS": round(abs(vl_aj), 2) if reg == "M510" else 0.0,
                "CNPJ_ESTAB": cnpj,
                "COD_AJ": str(row.get("COD_AJ", "") or ""),
                "DESCR_AJ": str(row.get("DESCR_AJ", "") or ""),
                "IND_AJ": str(row.get("IND_AJ", "") or ""),
            })
    for reg, aliq in (("M215", ALIQ_M215), ("M615", ALIQ_M615)):
        df_m = dfs.get(reg, pd.DataFrame())
        for _, row in df_m.iterrows():
            ind_aj = str(row.get("IND_AJ_BC", "0"))
            cod_aj = str(row.get("COD_AJ_BC", "")).strip()
            if ind_aj == "0" and not cod_aj:
                continue
            valor = round(abs(_to_float(row.get("VL_AJ_BC", 0))) * aliq, 2)
            if valor <= TOLERANCIA:
                continue
            linhas.append({
                "REG": reg, "NUM_DOC": str(row.get("NUM_DOC", "") or ""),
                "VL_PIS":    valor if reg == "M215" else 0.0,
                "VL_COFINS": valor if reg == "M615" else 0.0,
                "CNPJ_ESTAB": cnpj, "COD_AJ_BC": cod_aj,
                "DESCR_AJ_BC": DESCR_COD_AJ_BC.get(cod_aj, str(row.get("DESCR_AJ_BC", "") or "")),
                "IND_AJ_BC": ind_aj,
            })
    return linhas


def _normaliza_f120_para_comparacao(dfs: dict) -> list:
    f120 = dfs.get("F120", pd.DataFrame())
    if f120.empty:
        return []
    linhas = []
    for _, row in f120.iterrows():
        vl_pis    = _to_float(row.get("VL_PIS", 0))
        vl_cofins = _to_float(row.get("VL_COFINS", 0))
        if abs(vl_pis) <= TOLERANCIA and abs(vl_cofins) <= TOLERANCIA:
            continue
        linhas.append({
            "REG": "F120", "NUM_DOC": "",
            "VL_PIS": round(abs(vl_pis), 2), "VL_COFINS": round(abs(vl_cofins), 2),
            "CNPJ_ESTAB": str(row.get("CNPJ_ESTAB", "") or ""),
            "IDENT_BEM_IMOB": str(row.get("IDENT_BEM_IMOB", "") or ""),
            "DESC_BEM_IMOB": str(row.get("DESC_BEM_IMOB", "") or ""),
            "IND_ORIG_CRED": str(row.get("IND_ORIG_CRED", "") or ""),
        })
    return linhas


# =============================================================================
# 10. ORQUESTRADOR
# =============================================================================
def _marcar(dfs: list, **cols):
    """Adiciona colunas constantes (ex.: Bloco='C') aos DataFrames não vazios."""
    for d in dfs:
        if not d.empty:
            for k, v in cols.items():
                d[k] = v


def compara_gera_diferenca(arquivo_sped: str, planilha_diario: str,
                           filtro_filial: Optional[str] = None) -> dict:
    dfs    = extrai_dados_sped(arquivo_sped)
    df_sap = extrai_dados_planilha_sap(planilha_diario)

    # ── Agregações base ───────────────────────────────────────────────────────
    sped_saidas, sped_entradas = _agregar_sped(dfs)
    sap_saidas, sap_entradas_raw = _agregar_sap(df_sap, filtro_filial)

    # ── A100 (serviços): casa por valor antes de consumir os documentos NFe ─────
    sped_a100_s, sped_a100_e = _agregar_sped_a100(dfs)
    ok_a_s_val, sped_a100_s, sap_saidas = reconciliar_a100_por_valor(sped_a100_s, sap_saidas)

    entradas_pool = sap_entradas_raw.copy()
    ok_a_e_val, sped_a100_e, entradas_pool = reconciliar_a100_por_valor(sped_a100_e, entradas_pool)

    a100_s_nums = set(sped_a100_s["NUM_DOC"].astype(str)) if not sped_a100_s.empty else set()
    a100_e_nums = set(sped_a100_e["NUM_DOC"].astype(str)) if not sped_a100_e.empty else set()

    sap_a100_s = (sap_saidas[sap_saidas["NUM_DOC"].isin(a100_s_nums)].copy()
                  if a100_s_nums else pd.DataFrame(columns=list(sap_saidas.columns)))
    if a100_s_nums:
        sap_saidas = sap_saidas[~sap_saidas["NUM_DOC"].isin(a100_s_nums)].copy()

    a100_raw = dfs.get("A100", pd.DataFrame())
    chv_nfse_lookup = (
        a100_raw[(a100_raw["IND_OPER"].astype(str) == "0") & a100_raw["CHV_NFSE"].notna()]
        [["NUM_DOC", "CHV_NFSE"]].drop_duplicates("NUM_DOC")
        if not a100_raw.empty else pd.DataFrame(columns=["NUM_DOC", "CHV_NFSE"]))
    sap_a100_e = (
        entradas_pool[entradas_pool["NUM_DOC"].isin(a100_e_nums)]
        .merge(chv_nfse_lookup, on="NUM_DOC", how="left").pipe(lambda d: d[d["CHV_NFSE"].notna()].copy())
        if a100_e_nums else pd.DataFrame(columns=list(sap_entradas_raw.columns) + ["CHV_NFSE"]))

    # ── Entradas NFe: remove docs já tratados em D100/C500/A100 (evita dupla contagem) ─
    excluir_nfe = (
        (set(dfs["D100"]["NUM_DOC"].astype(str)) if not dfs["D100"].empty else set())
        | (set(dfs["C500"]["NUM_DOC"].astype(str)) if not dfs["C500"].empty else set())
        | a100_e_nums)
    entradas_nfe = (sap_entradas_raw[~sap_entradas_raw["NUM_DOC"].isin(excluir_nfe)]
                    if excluir_nfe else sap_entradas_raw)
    # CHV só das entradas creditáveis do SPED (não-creditáveis dariam falso "só SAP").
    chv_lookup = (sped_entradas[["NUM_DOC", "CHV_NFE"]].drop_duplicates("NUM_DOC")
                  if not sped_entradas.empty and "CHV_NFE" in sped_entradas.columns
                  else pd.DataFrame(columns=["NUM_DOC", "CHV_NFE"]))
    sap_entradas = entradas_nfe.merge(chv_lookup, on="NUM_DOC", how="left")

    # ── Transporte (CT-e) ───────────────────────────────────────────────────────
    sped_transp = _agregar_sped_d(dfs)
    chv_cte_lookup = (dfs["D100"][["NUM_DOC", "CHV_CTE"]].drop_duplicates("NUM_DOC")
                      if not dfs["D100"].empty else pd.DataFrame())
    sap_transp = sap_entradas_raw.copy()
    if "VL_SERV_SAP" not in sap_transp.columns:
        sap_transp["VL_SERV_SAP"] = 0.0
    sap_transp = sap_transp[sap_transp.get("VL_SERV_SAP", 0) != 0].copy()
    if not chv_cte_lookup.empty:
        sap_transp = sap_transp.merge(chv_cte_lookup, on="NUM_DOC", how="left")
    if "CHV_CTE" not in sap_transp.columns:
        sap_transp["CHV_CTE"] = pd.Series(dtype=str)

    # ── Reconciliações ──────────────────────────────────────────────────────────
    # A EFD-Contribuições escritura apenas PIS/PASEP, COFINS e CPRB. ICMS, IPI,
    # valor da mercadoria (ITEM) e valor do serviço (SERV) constam dos registros
    # somente como base/contexto e NÃO são a contribuição — por isso a
    # reconciliação confronta exclusivamente PIS e COFINS. (Manual EFD-Contrib.)
    cmp_piscof = {"PIS": ("VL_PIS", "VL_PIS_SAP"),
                  "COFINS": ("VL_COFINS", "VL_COFINS_SAP")}
    cmp_transp = {"PIS_D": ("VL_PIS_D", "VL_PIS_SAP"),
                  "COFINS_D": ("VL_COFINS_D", "VL_COFINS_SAP")}

    rec_s = reconciliar(sped_saidas,   sap_saidas,   cmp_piscof, chave="NUM_DOC")
    rec_e = reconciliar(sped_entradas, sap_entradas, cmp_piscof, chave="CHV_NFE")
    rec_t = reconciliar(sped_transp,   sap_transp,   cmp_transp, chave="CHV_CTE")

    # Energia (C500)
    sped_c500 = _agregar_sped_c500(dfs)
    c500_nums = set(sped_c500["NUM_DOC"].astype(str)) if not sped_c500.empty else set()
    sap_c500 = (sap_entradas_raw[sap_entradas_raw["NUM_DOC"].isin(c500_nums)].copy()
                if c500_nums else pd.DataFrame(columns=["NUM_DOC"]))
    cmp_c500 = {"PIS": ("VL_PIS_C5", "VL_PIS_SAP"), "COFINS": ("VL_COFINS_C5", "VL_COFINS_SAP")}
    rec_c5 = reconciliar(sped_c500, sap_c500, cmp_c500, chave="NUM_DOC")
    _marcar([rec_c5.divergencias, rec_c5.ok, rec_c5.so_sped, rec_c5.so_sap], _c500=True)

    # F100
    sped_f100 = _agregar_sped_f100(dfs)
    sap_f100, lc_contas_f100 = _agregar_sap_f100(df_sap)
    sap_f120_totais = _agregar_sap_f120(df_sap)
    excluir_f = {CONTA_PIS_RECUPERAR, CONTA_COFINS_RECUPERAR}
    nome_f100 = {str(r.get("Cta.contáb./cód.PN", "")).strip(): str(r.get("Cta.cont./Nome PN", "")).strip()
                 for _, r in df_sap.iterrows()
                 if str(r.get("Cta.cont./Nome PN", "")).strip() not in excluir_f}
    rec_f = reconciliar(sped_f100, sap_f100, cmp_piscof, chave="COD_CTA",
                        extra_cols=["IND_OPER", "DESC_DOC_OPER"])
    for d in (rec_f.divergencias, rec_f.ok, rec_f.so_sped):
        if not d.empty and "COD_CTA" in d.columns:
            d.insert(1, "NOME_CONTA", d["COD_CTA"].map(nome_f100).fillna(""))

    # A100 por número (complementa o casamento por valor)
    rec_a_s = reconciliar(sped_a100_s, sap_a100_s, cmp_piscof, chave="NUM_DOC")
    rec_a_e = reconciliar(sped_a100_e, sap_a100_e, cmp_piscof, chave="CHV_NFSE")
    ok_a_s = pd.concat([ok_a_s_val, rec_a_s.ok], ignore_index=True)
    ok_a_e = pd.concat([ok_a_e_val, rec_a_e.ok], ignore_index=True)
    _marcar([rec_a_s.divergencias, ok_a_s, rec_a_s.so_sped, rec_a_s.so_sap,
             rec_a_e.divergencias, ok_a_e, rec_a_e.so_sped, rec_a_e.so_sap], _a100=True)

    # ── Lançamentos de ajuste (divergências) ────────────────────────────────────
    vazio = pd.DataFrame()
    lanc_s  = gera_lancamentos_ajuste(rec_s.divergencias, df_sap) if not rec_s.divergencias.empty else vazio
    lanc_t  = gera_lancamentos_ajuste(rec_t.divergencias, df_sap) if not rec_t.divergencias.empty else vazio
    lanc_c5 = gera_lancamentos_ajuste(rec_c5.divergencias, df_sap) if not rec_c5.divergencias.empty else vazio
    lanc_f  = gera_lancamentos_ajuste_f100(rec_f.divergencias, lc_contas=lc_contas_f100)
    div_a   = pd.concat([rec_a_s.divergencias, rec_a_e.divergencias], ignore_index=True)
    lanc_a  = gera_lancamentos_ajuste(div_a, df_sap) if not div_a.empty else vazio
    _marcar([lanc_s], Bloco="C");   _marcar([lanc_t], Bloco="D")
    _marcar([lanc_c5], Bloco="C500"); _marcar([lanc_f], Bloco="F100"); _marcar([lanc_a], Bloco="A100")
    df_lanc = pd.concat([lanc_s, lanc_t, lanc_c5, lanc_f, lanc_a], ignore_index=True)

    # ── Lançamentos do que só existe no SPED ────────────────────────────────────
    ss_c  = gera_lancamentos_so_sped(df_sap, rec_e.so_sped, vazio, vazio, vazio)
    ss_d  = gera_lancamentos_so_sped(df_sap, vazio, rec_t.so_sped, vazio, vazio)
    ss_f  = gera_lancamentos_so_sped(df_sap, vazio, vazio, rec_f.so_sped, vazio)
    ss_c5 = gera_lancamentos_so_sped(df_sap, vazio, vazio, vazio, rec_c5.so_sped)
    ss_a_src = pd.concat([rec_a_s.so_sped, rec_a_e.so_sped], ignore_index=True)
    if not ss_a_src.empty:
        if "NUM_DOC" not in ss_a_src.columns:
            ss_a_src["NUM_DOC"] = ""
        falta = ss_a_src["NUM_DOC"].isna() | (ss_a_src["NUM_DOC"].astype(str) == "")
        if "CHV_NFSE" in ss_a_src.columns:
            ss_a_src.loc[falta, "NUM_DOC"] = ss_a_src.loc[falta, "CHV_NFSE"].fillna("")
    ss_a = gera_lancamentos_so_sped(df_sap, ss_a_src, vazio, vazio, vazio)
    _marcar([ss_c], Bloco="C"); _marcar([ss_d], Bloco="D"); _marcar([ss_f], Bloco="F100")
    _marcar([ss_c5], Bloco="C500"); _marcar([ss_a], Bloco="A100")
    df_lanc_so_sped = pd.concat([ss_c, ss_d, ss_f, ss_c5, ss_a], ignore_index=True)

    # ── Blocos M e F120 ──────────────────────────────────────────────────────────
    lanc_m   = gera_lancamentos_m110_m510(dfs);  _marcar([lanc_m], Bloco="M110_M510")
    lanc_m2  = gera_lancamentos_m215_m615(dfs);  _marcar([lanc_m2], Bloco="M215_M615")
    lanc_f120       = gera_lancamentos_f120(dfs);                       _marcar([lanc_f120], Bloco="F120")
    lanc_f120_delta = gera_lancamentos_f120_delta(dfs, sap_f120_totais); _marcar([lanc_f120_delta], Bloco="F120")

    so_sped_m    = _normaliza_m_para_comparacao(dfs)
    so_sped_f120 = _normaliza_f120_para_comparacao(dfs)
    f120_df = dfs.get("F120", pd.DataFrame())
    comparacao_f120 = [{
        "REG": "F120",
        "VL_PIS":        round(f120_df["VL_PIS"].apply(_to_float).sum(), 2),
        "VL_PIS_SAP":    sap_f120_totais.get("VL_PIS_SAP", 0.0),
        "VL_COFINS":     round(f120_df["VL_COFINS"].apply(_to_float).sum(), 2),
        "VL_COFINS_SAP": sap_f120_totais.get("VL_COFINS_SAP", 0.0),
    }] if not f120_df.empty else []

    # ── Estorno do que só existe no SAP ──────────────────────────────────────────
    so_sap_com_num = pd.concat(
        [d for d in [rec_s.so_sap, rec_e.so_sap, rec_t.so_sap, rec_c5.so_sap]
         if not d.empty and "NUM_DOC" in d.columns and "TIPO_DOC" in d.columns],
        ignore_index=True)
    sped_todos_nums = (
        (set(dfs["C100"]["NUM_DOC"].astype(str)) if not dfs["C100"].empty else set())
        | (set(dfs["D100"]["NUM_DOC"].astype(str)) if not dfs["D100"].empty else set())
        | (set(dfs["C500"]["NUM_DOC"].astype(str)) if not dfs["C500"].empty else set())
        | a100_s_nums | a100_e_nums)
    if sped_todos_nums:
        so_sap_com_num = so_sap_com_num[~so_sap_com_num["NUM_DOC"].isin(sped_todos_nums)].copy()
        so_sap_saida = rec_s.so_sap
        if "NUM_DOC" in so_sap_saida.columns:
            so_sap_saida = so_sap_saida[~so_sap_saida["NUM_DOC"].isin(sped_todos_nums)].reset_index(drop=True)
    else:
        so_sap_saida = rec_s.so_sap
    lanc_estorno = gera_lancamentos_estorno_so_sap(so_sap_com_num, df_sap)
    _marcar([lanc_estorno], Bloco="Desconhecido")

    # ── Retorno ──────────────────────────────────────────────────────────────────
    resultado = {
        "divergencias_saida":      rec_s.divergencias,
        "divergencias_entrada":    rec_e.divergencias,
        "ok_saida":                rec_s.ok,
        "ok_entrada":              rec_e.ok,
        "so_sped_saida":           rec_s.so_sped,
        "so_sped_entrada":         rec_e.so_sped,
        "so_sap_saida":            so_sap_saida,
        "divergencias_transporte": rec_t.divergencias,
        "ok_transporte":           rec_t.ok,
        "so_sped_transporte":      rec_t.so_sped,
        "so_sap_transporte":       rec_t.so_sap,
        "divergencias_f100":       rec_f.divergencias,
        "ok_f100":                 rec_f.ok,
        "so_sped_f100":            rec_f.so_sped,
        "so_sap_f100":             rec_f.so_sap,
        "divergencias_c500":       rec_c5.divergencias,
        "ok_c500":                 rec_c5.ok,
        "so_sped_c500":            rec_c5.so_sped,
        "so_sap_c500":             rec_c5.so_sap,
        "lancamentos":             df_lanc,
        "lancamentos_so_sped":     df_lanc_so_sped,
    }

    # Variantes JSON e blocos só-exibição.
    json_map = {
        "divergencias_saida": rec_s.divergencias, "divergencias_entrada": rec_e.divergencias,
        "ok_saida": rec_s.ok, "ok_entrada": rec_e.ok,
        "so_sped_saida": rec_s.so_sped, "so_sped_entrada": rec_e.so_sped,
        "so_sap_saida": so_sap_saida, "so_sap_entrada": rec_e.so_sap,
        "divergencias_transporte": rec_t.divergencias, "ok_transporte": rec_t.ok,
        "so_sped_transporte": rec_t.so_sped, "so_sap_transporte": rec_t.so_sap,
        "divergencias_f100": rec_f.divergencias, "ok_f100": rec_f.ok,
        "so_sped_f100": rec_f.so_sped, "so_sap_f100": rec_f.so_sap,
        "divergencias_c500": rec_c5.divergencias, "ok_c500": rec_c5.ok,
        "so_sped_c500": rec_c5.so_sped, "so_sap_c500": rec_c5.so_sap,
        "lancamentos": df_lanc, "lancamentos_so_sped": df_lanc_so_sped,
        "lancamentos_estorno_so_sap": lanc_estorno,
        "lancamentos_m110_m510": lanc_m, "lancamentos_m215_m615": lanc_m2,
        "lancamentos_f120": lanc_f120, "lancamentos_f120_delta": lanc_f120_delta,
        "divergencias_a100_saida": rec_a_s.divergencias, "ok_a100_saida": ok_a_s,
        "so_sped_a100_saida": rec_a_s.so_sped, "so_sap_a100_saida": rec_a_s.so_sap,
        "divergencias_a100_entrada": rec_a_e.divergencias, "ok_a100_entrada": ok_a_e,
        "so_sped_a100_entrada": rec_a_e.so_sped, "so_sap_a100_entrada": rec_a_e.so_sap,
    }
    for nome, df in json_map.items():
        resultado[f"{nome}_json"] = _df_para_json(df)
    resultado["so_sped_m_json"]       = so_sped_m
    resultado["so_sped_f120_json"]    = so_sped_f120
    resultado["comparacao_f120_json"] = comparacao_f120
    return resultado
