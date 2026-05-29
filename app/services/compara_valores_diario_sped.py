_CAMPOS = ("vl_doc", "vl_icms", "vl_pis", "vl_cofins", "vl_cbs", "vl_ibs")


def _valores_sped(nota: dict) -> dict:
    return {
        "vl_doc": nota.get("vl_doc", 0.0),
        "vl_icms": nota.get("vl_icms", 0.0),
        "vl_pis": nota.get("vl_pis", 0.0),
        "vl_cofins": nota.get("vl_cofins", 0.0),
        "vl_cbs": 0.0,
        "vl_ibs": 0.0,
    }


def comparar_por_nota(
    notas_sap: dict,
    notas_sped: dict,
    mapeamento: dict | None = None,
) -> dict:
    """
    Compara valores por nota entre o diário SAP e o SPED.

    notas_sap  : retorno de extrai_dados_planilha_sap.extrair_por_nota()
                 — a chave já é a chave de confronto (número NF ou cod_part)
    notas_sped : retorno de extrai_dados_sped.extrair_por_nota()
    mapeamento : dict opcional {chave_sap → chave_sped} para casos especiais

    Retorno:
        {
            "38639": {
                "chave_sap":   "38639",
                "chave_sped":  "38639",
                "status":      "encontrado" | "sem_sped" | "sem_sap",
                "sap":  {"vl_doc": 347.0, "vl_icms": 19.43, ...},
                "sped": {"vl_doc": 347.0, "vl_icms": 19.43, ...},
                "diferenca": {"vl_doc": 0.0, ...},   # sap - sped
                "centro_custo": "OBRAS",
                "contas": {"vl_pis": {"conta_debito": ..., "conta_credito": ...}, ...}
            }, ...
        }
    """
    mapeamento = mapeamento or {}
    resultado: dict = {}
    sped_casadas: set = set()

    for chave_sap, nota_sap in notas_sap.items():
        chave_sped = mapeamento.get(chave_sap, chave_sap)
        nota_sped = notas_sped.get(chave_sped)

        sap_vals = {c: nota_sap.get(c, 0.0) for c in _CAMPOS}

        if nota_sped is not None:
            sped_vals = _valores_sped(nota_sped)
            diferenca = {c: round(sap_vals[c] - sped_vals[c], 2) for c in _CAMPOS}
            status = "encontrado"
            sped_casadas.add(chave_sped)
        else:
            sped_vals = None
            diferenca = None
            status = "sem_sped"

        chave_result = chave_sped if nota_sped is not None else chave_sap
        resultado[chave_result] = {
            "chave_sap": chave_sap,
            "chave_sped": chave_sped if nota_sped is not None else None,
            "status": status,
            "sap": sap_vals,
            "sped": sped_vals,
            "diferenca": diferenca,
            "centro_custo": nota_sap.get("centro_custo", ""),
            "contas": nota_sap.get("contas", {}),
        }

    for chave_sped, nota_sped in notas_sped.items():
        if chave_sped in sped_casadas:
            continue
        resultado[chave_sped] = {
            "chave_sap": None,
            "chave_sped": chave_sped,
            "status": "sem_sap",
            "sap": None,
            "sped": _valores_sped(nota_sped),
            "diferenca": None,
        }

    return resultado
