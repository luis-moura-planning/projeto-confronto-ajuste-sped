import pandas as pd


# Situações de nota que devem ser excluídas da apuração fiscal.
# 02 = cancelada, 08 = numeração inutilizada.
# Referência: Manual EFD-Contribuições, Tabela de COD_SIT do C100.
COD_SIT_EXCLUIR = {"02", "08"}


def extrai_dados_sped(sped_txt: str) -> dict:
    """
    Lê um arquivo EFD-Contribuições (PIS/COFINS) e retorna um dict de DataFrames
    com os registros 0000, C100 e C170.

    Correções aplicadas em relação à versão anterior:
    --------------------------------------------------
    [FIX-1] Notas canceladas/inutilizadas excluídas do resultado.
        COD_SIT em {02, 08} -> linhas C100 e seus C170 filhos são descartados.
        Antes: todas as notas eram retornadas, inclusive canceladas.

    [FIX-2] IND_OPER preservado explicitamente no C100.
        O campo já existia no layout, mas agora é garantido que nunca seja
        coercido ou descartado antes de chegar ao chamador, pois
        compara_gera_diferenca precisa separar entradas (0) de saídas (1).

    Campos retornados por registro
    --------------------------------
    0000 : metadados do arquivo (empresa, CNPJ, período).
    C100 : cabeçalho de cada nota fiscal válida.
           Inclui IND_OPER (0 = entrada, 1 = saída), NUM_DOC, CHV_NFE e
           todos os campos financeiros (VL_MERC, VL_PIS, VL_COFINS, VL_ICMS).
    C170 : itens das notas; CHV_NFE propagado a partir do C100 pai.
           Inclui VL_ITEM, VL_PIS, VL_COFINS, VL_ICMS por item.
    """
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
    }

    dados = {"0000": [], "C100": [], "C170": []}
    nota_atual_chv = ""
    nota_atual_valida = True  # [FIX-1]

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
                    # [FIX-1] Verifica situação antes de aceitar a nota
                    cod_sit = registro.get("COD_SIT", "")
                    nota_atual_valida = cod_sit not in COD_SIT_EXCLUIR
                    nota_atual_chv = registro.get("CHV_NFE", "")
                    if not nota_atual_valida:
                        continue
                    registro["CHV_NFE"] = nota_atual_chv
                    dados["C100"].append(registro)

                elif reg == "C170":
                    # [FIX-1] Descarta itens de notas canceladas
                    if not nota_atual_valida:
                        continue
                    registro["CHV_NFE"] = nota_atual_chv
                    dados["C170"].append(registro)

                else:
                    dados[reg].append(registro)

    except FileNotFoundError:
        raise ValueError(f"Arquivo nao encontrado: {sped_txt}")
    except UnicodeDecodeError:
        raise ValueError("Erro de encoding ao ler o arquivo SPED (latin1)")

    return {reg: pd.DataFrame(lista) for reg, lista in dados.items()}
