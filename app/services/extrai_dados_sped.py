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

        "D100": [
            "REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", "COD_SIT",
            "SER", "SUB", "NUM_DOC", "CHV_CTE", "DT_DOC", "DT_A_P",
            "TP_CT-e", "CHV_CTE_REF", "VL_DOC", "VL_DESC", "IND_FRT",
            "VL_SERV", "VL_BC_ICMS", "VL_ICMS", "VL_NT", "COD_INF",
            "COD_CTA",
        ],

        "D101": [
            "REG", "IND_NAT_FRT", "VL_ITEM", "CST_PIS", "NAT_BC_CRED",
            "VL_BC_PIS", "ALIQ_PIS", "VL_PIS", "COD_CTA",
        ],

        "D105": [
            "REG", "IND_NAT_FRT", "VL_ITEM", "CST_COFINS", "NAT_BC_CRED",
            "VL_BC_COFINS", "ALIQ_COFINS", "VL_COFINS", "COD_CTA",
        ],

        "C500": [
            "REG", "COD_PART", "COD_MOD", "COD_SIT", "SER", "SUB",
            "NUM_DOC", "DT_DOC", "DT_ENT", "VL_DOC", "VL_ICMS", "COD_INF",
            "VL_PIS", "VL_COFINS", "CHV_DOCe",
        ],

        "C501": [
            "REG", "CST_PIS", "VL_ITEM", "NAT_BC_CRED",
            "VL_BC_PIS", "ALIQ_PIS", "VL_PIS", "COD_CTA",
        ],
  
        "C505": [
            "REG", "CST_COFINS", "VL_ITEM", "NAT_BC_CRED",
            "VL_BC_COFINS", "ALIQ_COFINS", "VL_COFINS", "COD_CTA",
        ],

        "F100": [
            "REG", "IND_OPER", "COD_PART", "COD_ITEM", "DT_OPER", "VL_OPER",
            "CST_PIS", "VL_BC_PIS", "ALIQ_PIS", "VL_PIS",
            "CST_COFINS", "VL_BC_COFINS", "ALIQ_COFINS", "VL_COFINS",
            "NAT_BC_CRED", "IND_ORIG_CRED", "COD_CTA", "COD_CCUS", "DESC_DOC_OPER",
        ],

        "F120": [
            "REG", "NAT_BC_CRED", "IDENT_BEM_IMOB", "IND_ORIG_CRED",
            "IND_UTIL_BEM_IMOB", "VL_OPER_DEP", "PARC_OPER_NAO_BC_CRED",
            "CST_PIS", "VL_BC_PIS", "ALIQ_PIS", "VL_PIS",
            "CST_COFINS", "VL_BC_COFINS", "ALIQ_COFINS", "VL_COFINS",
            "COD_CTA", "COD_CCUS", "DESC_BEM_IMOB",
        ],

        "M110": [
            "REG", "IND_AJ", "VL_AJ", "COD_AJ", "NUM_DOC", "DESCR_AJ", "DT_REF",
        ],

        "M215": [
            "REG", "IND_AJ_BC", "VL_AJ_BC", "COD_AJ_BC", "NUM_DOC",
            "DESCR_AJ_BC", "DT_REF", "COD_CTA", "CNPJ", "INFO_COMPL",
        ],

        "M510": [
            "REG", "IND_AJ", "VL_AJ", "COD_AJ", "NUM_DOC", "DESCR_AJ", "DT_REF",
        ],

        "M615": [
            "REG", "IND_AJ_BC", "VL_AJ_BC", "COD_AJ_BC", "NUM_DOC",
            "DESCR_AJ_BC", "DT_REF", "COD_CTA", "CNPJ", "INFO_COMPL",
        ],

        "A100": [
            "REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_SIT", "SER", "SUB",
            "NUM_DOC", "CHV_NFSE", "DT_DOC", "DT_EXE_SERV", "VL_DOC",
            "IND_PGTO", "VL_DESC", "VL_BC_PIS", "VL_PIS", "VL_BC_COFINS",
            "VL_COFINS", "VL_PIS_RET", "VL_COFINS_RET", "VL_ISS",
        ],

        "A110": [
            "REG", "COD_INF", "TXT_COMPL",
        ],

        "A111": [
            "REG", "NUM_PROC", "IND_PROC",
        ],

        "A120": [
            "REG", "VL_TOT_SERV", "VL_BC_PIS", "VL_PIS_IMP", "DT_PAG_PIS",
            "VL_BC_COFINS", "VL_COFINS_IMP", "DT_PAG_COFINS", "LOC_EXE_SERV",
        ],

        "A170": [
            "REG", "NUM_ITEM", "COD_ITEM", "DESCR_COMPL", "VL_ITEM", "VL_DESC",
            "NAT_BC_CRED", "IND_ORIG_CRED", "CST_PIS", "VL_BC_PIS", "ALIQ_PIS",
            "VL_PIS", "CST_COFINS", "VL_BC_COFINS", "ALIQ_COFINS", "VL_COFINS",
            "COD_CTA", "COD_CCUS",
        ],
    }

    dados = {"0000": [], "C100": [], "C170": [], "C500": [], "C501": [], "C505": [], "D100": [], "D101": [], "D105": [], "F100": [], "F120": [], "M110": [], "M215": [], "M510": [], "M615": [], "A100": [], "A110": [], "A111": [], "A120": [], "A170": []}

    cnpj_atual = ""
    nota_atual_chv = ""
    nota_atual_valida = True

    c500_atual_chv = ""
    c500_atual_num = ""
    c500_atual_valida = True

    d100_atual_chv = ""
    d100_atual_valida = True

    a100_atual_chv = ""
    a100_atual_num = ""
    a100_atual_valida = True

    try:
        with open(sped_txt, "r", encoding="latin1") as arquivo:
            for linha in arquivo:
                linha = linha.strip()
                if not linha:
                    continue

                campos = linha.strip("|").split("|")
                reg = campos[0]


                if reg in ("A010", "C010", "D010", "F010", "M010"):
                    cnpj_atual = campos[1] if len(campos) > 1 else ""
                    continue

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
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados["C100"].append(registro)

                elif reg == "C170":
                    if not nota_atual_valida:
                        continue
                    registro["CHV_NFE"] = nota_atual_chv
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados["C170"].append(registro)

                elif reg == "C500":
                    cod_sit = registro.get("COD_SIT", "")
                    c500_atual_valida = cod_sit not in COD_SIT_EXCLUIR
                    c500_atual_chv = registro.get("CHV_DOCe", "")
                    c500_atual_num = registro.get("NUM_DOC", "")
                    if not c500_atual_valida:
                        continue
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados["C500"].append(registro)

                elif reg in ("C501", "C505"):
                    if not c500_atual_valida:
                        continue
                    registro["CHV_DOCe"] = c500_atual_chv
                    registro["NUM_DOC"] = c500_atual_num
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados[reg].append(registro)

                elif reg == "D100":
                    cod_sit = registro.get("COD_SIT", "")
                    d100_atual_valida = cod_sit not in COD_SIT_EXCLUIR
                    d100_atual_chv = registro.get("CHV_CTE", "")
                    if not d100_atual_valida:
                        continue
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados["D100"].append(registro)

                elif reg in ("D101", "D105"):
                    if not d100_atual_valida:
                        continue
                    registro["CHV_CTE"] = d100_atual_chv
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados[reg].append(registro)

                elif reg == "F100":
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados["F100"].append(registro)

                elif reg == "F120":
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados["F120"].append(registro)

                elif reg in ("M110", "M215", "M510", "M615"):
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados[reg].append(registro)

                elif reg == "A100":
                    cod_sit = registro.get("COD_SIT", "")
                    a100_atual_valida = cod_sit not in COD_SIT_EXCLUIR
                    a100_atual_chv = registro.get("CHV_NFSE", "")
                    a100_atual_num = registro.get("NUM_DOC", "")
                    if not a100_atual_valida:
                        continue
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados["A100"].append(registro)

                elif reg in ("A110", "A111", "A120", "A170"):
                    if not a100_atual_valida:
                        continue
                    registro["CHV_NFSE"] = a100_atual_chv
                    registro["NUM_DOC"]  = a100_atual_num
                    registro["CNPJ_ESTAB"] = cnpj_atual
                    dados[reg].append(registro)

                else:
                    dados[reg].append(registro)

    except FileNotFoundError:
        raise ValueError(f"Arquivo nao encontrado: {sped_txt}")
    except UnicodeDecodeError:
        raise ValueError("Erro de encoding ao ler o arquivo SPED (latin1)")

    return {reg: pd.DataFrame(lista) for reg, lista in dados.items()}
