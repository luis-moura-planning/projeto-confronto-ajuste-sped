import re
from typing import Optional

import pandas as pd

# ── Mapeamento conta → (campo, lado) ─────────────────────────────────────────
# lado: 'credito' = conta "a Recolher" (passivo), 'debito' = conta de dedução
_CONTA_MAPEAMENTO = {
    "2.01.01.04.0001": ("vl_icms", "credito"),
    "2.01.01.04.0002": ("vl_pis", "credito"),
    "2.01.01.04.0003": ("vl_cofins", "credito"),
    "3.01.01.03.0003": ("vl_pis", "debito"),
    "3.01.01.03.0004": ("vl_cofins", "debito"),
    "3.01.01.03.0009": ("vl_cbs", "debito"),
    "3.01.01.03.0010": ("vl_ibs", "debito"),
}

# Lado que serve de base para acumulação (evita dupla contagem double-entry)
_ACUMULAR_LADO = {
    "vl_icms": "credito",
    "vl_pis": "credito",
    "vl_cofins": "credito",
    "vl_cbs": "debito",
    "vl_ibs": "debito",
}

_RE_CONTA_PARCEIRO = re.compile(r"^[CF]\d{5}$")


def _extrair_chave(obs: str) -> str:
    """
    Extrai a chave de confronto com o SPED a partir da Observação do SAP.

    'Ref a NF: 38639 - JUVENIL...' → '38639'
    Qualquer outro formato          → ''  (ignorar)
    """
    m = re.search(r"\bNF[:\s]+(\d+)", str(obs), re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def extrair_por_nota(
    caminho_arquivo: str,
    filtro_nota: Optional[str] = None,
) -> dict:
    """
    Lê a aba 'Diário' e retorna um dicionário agrupado pela Observação,
    com valores de tributos pré-calculados.

    A chave do dicionário é o número da NF extraído da Observação:
      - número da NF ('38639') para 'Ref a NF: 38639 - ...'
      - demais formatos são ignorados

    Retorno:
        {
            "38639": {
                "seq": 1, "num_transacao": ..., "data_lancamento": "2026-03-02",
                "serie": "Primário", "num_doc": "...", "observacoes": "Ref a NF: 38639...",
                "centro_custo": "OBRAS",
                "vl_doc": 347.0, "vl_icms": 19.43,
                "vl_pis": 0.0, "vl_cofins": 0.0, "vl_cbs": 0.0, "vl_ibs": 0.0,
                "contas": {
                    "vl_pis": {
                        "conta_debito": "3.01.01.03.0003", "desc_debito": "( - ) PIS/PASEP",
                        "conta_credito": "2.01.01.04.0002", "desc_credito": "PIS a Recolher"
                    }, ...
                }
            }, ...
        }
    """
    df = pd.read_excel(caminho_arquivo, sheet_name="Diário", header=0)
    df["Data de lançamento"] = pd.to_datetime(df["Data de lançamento"], errors="coerce")
    df["Débito/crédito (MC)"] = pd.to_numeric(
        df["Débito/crédito (MC)"], errors="coerce"
    )
    df["Observações"] = df["Observações"].ffill()

    if filtro_nota:
        mask = df["Observações"].str.contains(filtro_nota, case=False, na=False)
        df = df[mask]

    notas: dict = {}

    for obs, grupo in df.groupby("Observações", sort=False):
        chave = _extrair_chave(str(obs))
        if not chave:
            continue

        grupo = grupo.reset_index(drop=True)

        mask_cab = grupo["Nº seq."].notna()
        cab = grupo[mask_cab].iloc[0] if mask_cab.any() else grupo.iloc[0]

        data = cab["Data de lançamento"]
        data_str = data.strftime("%Y-%m-%d") if pd.notna(data) else str(data)

        totais = {k: 0.0 for k in _ACUMULAR_LADO}
        vl_doc = 0.0
        centro_custo = ""
        contas: dict = {}

        linhas_det = grupo[grupo["Nº seq."].isna()]

        for _, row in linhas_det.iterrows():
            conta = _str(row.get("Cta.contáb./cód.PN"))
            nome = _str(row.get("Cta.cont./Nome PN"))
            val = (
                float(row["Débito/crédito (MC)"])
                if pd.notna(row["Débito/crédito (MC)"])
                else 0.0
            )
            cc = _str(row.get("Centro de Custo"))

            if cc and not centro_custo:
                centro_custo = cc

            if _RE_CONTA_PARCEIRO.match(conta):
                vl_doc = abs(val)
                continue

            mapa = _CONTA_MAPEAMENTO.get(conta)
            if not mapa:
                continue

            campo, lado = mapa

            if lado == _ACUMULAR_LADO[campo]:
                totais[campo] += abs(val)

            if campo not in contas:
                contas[campo] = {}
            contas[campo][f"conta_{lado}"] = conta
            contas[campo][f"desc_{lado}"] = nome

        notas[chave] = {
            "seq": cab.get("Nº seq."),
            "num_transacao": cab.get("Nº transação"),
            "data_lancamento": data_str,
            "serie": cab.get("Série", ""),
            "num_doc": cab.get("Nº doc.", ""),
            "observacoes": str(obs),
            "centro_custo": centro_custo,
            "vl_doc": round(vl_doc, 2),
            "vl_icms": round(totais["vl_icms"], 2),
            "vl_pis": round(totais["vl_pis"], 2),
            "vl_cofins": round(totais["vl_cofins"], 2),
            "vl_cbs": round(totais["vl_cbs"], 2),
            "vl_ibs": round(totais["vl_ibs"], 2),
            "contas": contas,
        }

    return notas


def _str(val) -> str:
    return str(val).strip() if pd.notna(val) else ""
