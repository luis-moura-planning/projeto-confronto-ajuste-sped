import pandas as pd


def extrai_dados_sped(sped_txt):
    layouts = {
        "0000": [
            "REG",
            "COD_VER",
            "TIPO_ESCRIT",
            "IND_SIT_ESP",
            "NUM_REC_ANTERIOR",
            "DT_INI",
            "DT_FIN",
            "NOME",
            "CNPJ",
            "UF",
            "COD_MUN",
            "SUFRAMA",
            "IND_NAT_PJ",
            "IND_ATIV",
        ],
        "C100": [
            "REG",
            "IND_OPER",
            "IND_EMIT",
            "COD_PART",
            "COD_MOD",
            "COD_SIT",
            "SER",
            "NUM_DOC",
            "CHV_NFE",
            "DT_DOC",
            "DT_E_S",
            "VL_DOC",
            "IND_PGTO",
            "VL_DESC",
            "VL_ABAT_NT",
            "VL_MERC",
            "IND_FRT",
            "VL_FRT",
            "VL_SEG",
            "VL_OUT_DA",
            "VL_BC_ICMS",
            "VL_ICMS",
            "VL_BC_ICMS_ST",
            "VL_ICMS_ST",
            "VL_IPI",
            "VL_PIS",
            "VL_COFINS",
            "VL_PIS_ST",
            "VL_COFINS_ST",
        ],
        "C170": [
            "REG",
            "NUM_ITEM",
            "COD_ITEM",
            "DESCR_COMPL",  # CORREÇÃO: campo duplo separado
            "QTD",
            "UNID",
            "VL_ITEM",
            "VL_DESC",
            "IND_MOV",
            "CST_ICMS",
            "CFOP",
            "COD_NAT",
            "VL_BC_ICMS",
            "ALIQ_ICMS",
            "VL_ICMS",
            "VL_BC_ICMS_ST",
            "ALIQ_ST",
            "VL_ICMS_ST",
            "IND_APUR",
            "CST_IPI",
            "COD_ENQ",
            "VL_BC_IPI",
            "ALIQ_IPI",
            "VL_IPI",
            "CST_PIS",
            "VL_BC_PIS",
            "ALIQ_PIS",
            "QUANT_BC_PIS",
            "ALIQ_PIS_QUANT",
            "VL_PIS",
            "CST_COFINS",
            "VL_BC_COFINS",
            "ALIQ_COFINS",
            "QUANT_BC_COFINS",
            "ALIQ_COFINS_QUANT",
            "VL_COFINS",
            "COD_CTA",  # CORREÇÃO: campos faltantes
        ],
    }

    dados = {"0000": [], "C100": [], "C170": []}
    nota_atual = ""
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
                if reg in ("C100", "C170"):
                    if reg == "C100":
                        nota_atual = registro.get("CHV_NFE", "")
                    registro["CHV_NFE"] = nota_atual
                dados[reg].append(registro)
    except FileNotFoundError:
        raise ValueError(f"Arquivo não encontrado: {sped_txt}")
    except UnicodeDecodeError:
        raise ValueError("Erro de encoding ao ler o arquivo SPED (latin1)")

    return {reg: pd.DataFrame(lista) for reg, lista in dados.items()}
