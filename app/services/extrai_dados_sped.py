def _to_float(value: str) -> float:
    if not value or not value.strip():
        return 0.0
    return float(value.strip().replace(".", "").replace(",", "."))


def _parse_date(s: str) -> str:
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[6:8]}/{s[4:6]}/{s[0:4]}"
    return s


def extrair_por_nota(caminho_arquivo: str) -> dict:
    """
    Lê o SPED Contribuições e retorna um dicionário com uma entrada por nota.
    Cobre A100 (NFS-e serviços), C100/C170 (NF-e produtos) e C500/C501/C505
    (energia elétrica).

    Além das notas individuais, gera entradas agregadas por cod_part
    (chave "C01241" etc.) para confronto com lançamentos SAP do tipo
    'Notas Fiscais de Saída - C01241'.
    """
    participantes: dict = {}
    cnpj_estabelecimento = ""
    notas: dict = {}
    nota_atual = None
    _agg: dict = {}

    with open(caminho_arquivo, encoding="latin-1") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                continue

            campos = line.split("|")
            if len(campos) < 2:
                continue
            reg = campos[1]

            # ── Tabela de participantes ───────────────────────────────────
            if reg == "0150":
                cod = campos[2].strip()
                participantes[cod] = {
                    "nome": campos[3].strip(),
                    "cnpj": campos[5].strip() if len(campos) > 5 else "",
                    "cpf": campos[6].strip() if len(campos) > 6 else "",
                }

            elif reg == "C010":
                cnpj_estabelecimento = campos[2].strip()

            # ── A100: Notas Fiscais de Serviço ────────────────────────────
            # |A100|IND_OPER|IND_EMIT|COD_PART|COD_SIT|SER|SUB|NUM_DOC|CHV_NFSE|
            #  DT_DOC|DT_EXE_SERV|VL_DOC|VL_DESC|VL_BC_PIS|VL_BC_COFINS|VL_ISS|
            #  VL_PIS|VL_COFINS|...
            elif reg == "A100" and len(campos) >= 19:
                cod_part = campos[4].strip()
                part = participantes.get(cod_part, {})
                num_doc = campos[8].strip()
                nota_atual = num_doc
                notas[nota_atual] = {
                    "tipo_bloco": "A100",
                    "ind_oper": campos[2].strip(),
                    "ind_emit": campos[3].strip(),
                    "cod_part": cod_part,
                    "nome_part": part.get("nome", ""),
                    "num_doc": num_doc,
                    "dt_doc": _parse_date(campos[10]) if len(campos) > 10 else "",
                    "vl_doc": _to_float(campos[12]) if len(campos) > 12 else 0.0,
                    "vl_icms": 0.0,
                    "vl_pis": _to_float(campos[17]) if len(campos) > 17 else 0.0,
                    "vl_cofins": _to_float(campos[18]) if len(campos) > 18 else 0.0,
                    "itens": [],
                }
                _acumular_agg(_agg, cod_part, part, notas[nota_atual])

            # ── C100: NF-e produtos ───────────────────────────────────────
            elif reg == "C100":
                ind_emit = campos[3].strip()
                cod_part = campos[4].strip()
                part = participantes.get(cod_part, {})
                doc_part = part.get("cnpj") or part.get("cpf", "")

                cnpj_emit = cnpj_estabelecimento if ind_emit == "0" else doc_part
                cnpj_dest = doc_part if ind_emit == "0" else cnpj_estabelecimento

                num_doc = campos[8].strip()
                nota_atual = num_doc
                notas[nota_atual] = {
                    "tipo_bloco": "C100",
                    "ind_oper": campos[2].strip(),
                    "ind_emit": ind_emit,
                    "cod_part": cod_part,
                    "nome_part": part.get("nome", ""),
                    "cnpj_emit": cnpj_emit,
                    "cnpj_dest": cnpj_dest,
                    "cod_mod": campos[5].strip(),
                    "cod_sit": campos[6].strip(),
                    "serie": campos[7].strip(),
                    "num_doc": num_doc,
                    "chv_nfe": campos[9].strip() if len(campos) > 9 else "",
                    "dt_doc": campos[10].strip() if len(campos) > 10 else "",
                    "dt_ent_sai": campos[11].strip() if len(campos) > 11 else "",
                    "vl_doc": _to_float(campos[12]) if len(campos) > 12 else 0.0,
                    "vl_desc": _to_float(campos[14]) if len(campos) > 14 else 0.0,
                    "vl_merc": _to_float(campos[16]) if len(campos) > 16 else 0.0,
                    "vl_frt": _to_float(campos[18]) if len(campos) > 18 else 0.0,
                    "vl_seg": _to_float(campos[19]) if len(campos) > 19 else 0.0,
                    "vl_out_da": _to_float(campos[20]) if len(campos) > 20 else 0.0,
                    "vl_bc_icms": _to_float(campos[21]) if len(campos) > 21 else 0.0,
                    "vl_icms": _to_float(campos[22]) if len(campos) > 22 else 0.0,
                    "vl_bc_icms_st": _to_float(campos[23]) if len(campos) > 23 else 0.0,
                    "vl_icms_st": _to_float(campos[24]) if len(campos) > 24 else 0.0,
                    "vl_ipi": _to_float(campos[25]) if len(campos) > 25 else 0.0,
                    "vl_pis": _to_float(campos[26]) if len(campos) > 26 else 0.0,
                    "vl_cofins": _to_float(campos[27]) if len(campos) > 27 else 0.0,
                    "itens": [],
                }
                _acumular_agg(_agg, cod_part, part, notas[nota_atual])

            elif reg == "C170" and nota_atual is not None:
                notas[nota_atual]["itens"].append(
                    {
                        "num_item": campos[2].strip(),
                        "cod_item": campos[3].strip(),
                        "descr": campos[4].strip(),
                        "qtd": _to_float(campos[5]),
                        "unid": campos[6].strip(),
                        "vl_item": _to_float(campos[7]),
                        "cfop": campos[11].strip(),
                        "cst_icms": campos[10].strip() if len(campos) > 10 else "",
                        "vl_bc_icms": _to_float(campos[13])
                        if len(campos) > 13
                        else 0.0,
                        "aliq_icms": _to_float(campos[14]) if len(campos) > 14 else 0.0,
                        "vl_icms": _to_float(campos[15]) if len(campos) > 15 else 0.0,
                        "vl_pis": _to_float(campos[30]) if len(campos) > 30 else 0.0,
                        "vl_cofins": _to_float(campos[36]) if len(campos) > 36 else 0.0,
                        "cod_cta": campos[37].strip() if len(campos) > 37 else "",
                    }
                )

            # ── C500: energia elétrica / serviços ─────────────────────────
            elif reg == "C500":
                cod_part = campos[2].strip()
                part = participantes.get(cod_part, {})
                num_doc = campos[7].strip()
                nota_atual = num_doc
                notas[nota_atual] = {
                    "tipo_bloco": "C500",
                    "cod_part": cod_part,
                    "nome_part": part.get("nome", ""),
                    "num_doc": num_doc,
                    "dt_doc": campos[8].strip() if len(campos) > 8 else "",
                    "dt_ent_sai": campos[9].strip() if len(campos) > 9 else "",
                    "vl_doc": _to_float(campos[10]) if len(campos) > 10 else 0.0,
                    "vl_icms": 0.0,
                    "vl_pis": _to_float(campos[13]) if len(campos) > 13 else 0.0,
                    "vl_cofins": _to_float(campos[14]) if len(campos) > 14 else 0.0,
                    "itens": [],
                }
                _acumular_agg(_agg, cod_part, part, notas[nota_atual])

            elif reg == "C501" and nota_atual is not None:
                notas[nota_atual]["itens"].append(
                    {
                        "tipo": "pis",
                        "cst": campos[2].strip(),
                        "vl_bc": _to_float(campos[3]),
                        "vl": _to_float(campos[7]),
                    }
                )

            elif reg == "C505" and nota_atual is not None:
                notas[nota_atual]["itens"].append(
                    {
                        "tipo": "cofins",
                        "cst": campos[2].strip(),
                        "vl_bc": _to_float(campos[3]),
                        "vl": _to_float(campos[7]),
                    }
                )

    # Entradas agregadas por cod_part para confronto com lançamentos SAP do
    # tipo "Notas Fiscais de Saída - C01241" (soma de todas as notas do parceiro)
    for cod, vals in _agg.items():
        notas[cod] = {
            "tipo_bloco": "aggregate",
            "cod_part": cod,
            "nome_part": vals["nome_part"],
            "num_doc": cod,
            "vl_doc": round(vals["vl_doc"], 2),
            "vl_icms": round(vals["vl_icms"], 2),
            "vl_pis": round(vals["vl_pis"], 2),
            "vl_cofins": round(vals["vl_cofins"], 2),
            "itens": [],
        }

    return notas


def _acumular_agg(agg: dict, cod_part: str, part: dict, nota: dict) -> None:
    if not cod_part:
        return
    acc = agg.setdefault(
        cod_part,
        {
            "nome_part": part.get("nome", ""),
            "vl_doc": 0.0,
            "vl_icms": 0.0,
            "vl_pis": 0.0,
            "vl_cofins": 0.0,
        },
    )
    acc["vl_doc"] += nota.get("vl_doc", 0.0)
    acc["vl_icms"] += nota.get("vl_icms", 0.0)
    acc["vl_pis"] += nota.get("vl_pis", 0.0)
    acc["vl_cofins"] += nota.get("vl_cofins", 0.0)
