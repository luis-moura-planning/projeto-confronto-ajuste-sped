import pandas as pd

COD_SIT_EXCLUIR = {"02", "08"}


def extrai_dados_sped(sped_txt: str) -> dict:

    layouts = {
        "0000": [
            "REG", "COD_VER", "TIPO_ESCRIT", "IND_SIT_ESP", "NUM_REC_ANTERIOR",
            "DT_INI", "DT_FIN", "NOME", "CNPJ", "UF", "COD_MUN", "SUFRAMA",
            "IND_NAT_PJ", "IND_ATIV",
        ],
        "C100": [
            "REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", "COD_SIT",
            "SER", "NUM_DOC", "CHV_NFE", "DT_DOC", "DT_E_S", "VL_DOC",
            "IND_PGTO", "VL_DESC", "VL_ABAT_NT", "VL_MERC", "IND_FRT",
            "VL_FRT", "VL_SEG", "VL_OUT_DA", "VL_BC_ICMS", "VL_ICMS",
            "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_IPI", "VL_PIS", "VL_COFINS",
            "VL_PIS_ST", "VL_COFINS_ST",
        ],
        "C170": [
            "REG", "NUM_ITEM", "COD_ITEM", "DESCR_COMPL", "QTD", "UNID",
            "VL_ITEM", "VL_DESC", "IND_MOV", "CST_ICMS", "CFOP", "COD_NAT",
            "VL_BC_ICMS", "ALIQ_ICMS", "VL_ICMS", "VL_BC_ICMS_ST", "ALIQ_ST",
            "VL_ICMS_ST", "IND_APUR", "CST_IPI", "COD_ENQ", "VL_BC_IPI",
            "ALIQ_IPI", "VL_IPI", "CST_PIS", "VL_BC_PIS", "ALIQ_PIS",
            "QUANT_BC_PIS", "ALIQ_PIS_QUANT", "VL_PIS", "CST_COFINS",
            "VL_BC_COFINS", "ALIQ_COFINS", "QUANT_BC_COFINS", "ALIQ_COFINS_QUANT",
            "VL_COFINS", "COD_CTA",
        ],
        # Bloco D — Serviços de Transporte
        # D100: cabeçalho do documento (CT-e, CRT, etc.)
        "D100": [
            "REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", "COD_SIT",
            "SER", "SUB", "NUM_DOC", "CHV_CTE", "DT_DOC", "DT_A_P",
            "TP_CT-e", "CHV_CTE_REF", "VL_DOC", "VL_DESC", "IND_FRT",
            "VL_SERV", "VL_BC_ICMS", "VL_ICMS", "VL_NT", "COD_INF",
            "COD_CTA",
        ],
        # D101: complemento do D100 — PIS/Pasep
        "D101": [
            "REG", "IND_NAT_FRT", "VL_ITEM", "CST_PIS", "NAT_BC_CRED",
            "VL_BC_PIS", "ALIQ_PIS", "VL_PIS", "COD_CTA",
        ],
        # D105: complemento do D100 — Cofins
        "D105": [
            "REG", "IND_NAT_FRT", "VL_ITEM", "CST_COFINS", "NAT_BC_CRED",
            "VL_BC_COFINS", "ALIQ_COFINS", "VL_COFINS", "COD_CTA",
        ],
    }

    dados = {"0000": [], "C100": [], "C170": [], "D100": [], "D101": [], "D105": []}
    nota_atual_chv = ""
    nota_atual_valida = True
    # Controle de estado para o Bloco D
    d100_atual_chv = ""
    d100_atual_valida = True

    try:
        with open(sped_txt, "r", encoding="latin1") as arquivo:
            for linha in arquivo:
                linha = linha.strip()
                if not linha:
                    continue

                campos = linha.strip("|").split("|")
                reg = campos[0]
                if reg not in layouts:
                    continue

                nomes_campos = layouts[reg]
                if len(campos) < len(nomes_campos):
                    campos.extend([""] * (len(nomes_campos) - len(campos)))

                registro = dict(zip(nomes_campos, campos))

                if reg == "C100":
                    cod_sit = registro.get("COD_SIT", "")
                    nota_atual_valida = cod_sit not in COD_SIT_EXCLUIR
                    nota_atual_chv = registro.get("CHV_NFE", "")
                    if not nota_atual_valida:
                        continue
                    registro["CHV_NFE"] = nota_atual_chv
                    dados["C100"].append(registro)

                elif reg == "C170":
                    if not nota_atual_valida:
                        continue
                    registro["CHV_NFE"] = nota_atual_chv
                    dados["C170"].append(registro)

                elif reg == "D100":
                    cod_sit = registro.get("COD_SIT", "")
                    d100_atual_valida = cod_sit not in COD_SIT_EXCLUIR
                    d100_atual_chv = registro.get("CHV_CTE", "")
                    if not d100_atual_valida:
                        continue
                    dados["D100"].append(registro)

                elif reg in ("D101", "D105"):
                    # Filhos do D100 — herdam a chave do CT-e pai
                    if not d100_atual_valida:
                        continue
                    registro["CHV_CTE"] = d100_atual_chv
                    dados[reg].append(registro)

                else:
                    dados[reg].append(registro)

    except FileNotFoundError:
        raise ValueError(f"Arquivo nao encontrado: {sped_txt}")
    except UnicodeDecodeError:
        raise ValueError("Erro de encoding ao ler o arquivo SPED (latin1)")

    return {reg: pd.DataFrame(lista) for reg, lista in dados.items()}
