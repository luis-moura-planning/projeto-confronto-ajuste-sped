def _to_float(value: str) -> float:
    if not value or not value.strip():
        return 0.0
    return float(value.strip().replace('.', '').replace(',', '.'))


def extrair_por_nota(caminho_arquivo: str) -> dict:

    # 0150: cod_part → {nome, cnpj, cpf}
    participantes: dict = {}
    cnpj_estabelecimento = ''

    notas = {}
    nota_atual = None

    with open(caminho_arquivo, encoding='latin-1') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if not line:
                continue

            campos = line.split('|')
            if len(campos) < 2:
                continue
            reg = campos[1]

            if reg == '0150':
                # 1=REG 2=COD_PART 3=NOME 4=COD_PAIS 5=CNPJ 6=CPF
                cod = campos[2].strip()
                participantes[cod] = {
                    'nome': campos[3].strip(),
                    'cnpj': campos[5].strip() if len(campos) > 5 else '',
                    'cpf':  campos[6].strip() if len(campos) > 6 else '',
                }

            elif reg == 'C010':
                # 1=REG 2=CNPJ_ESTAB
                cnpj_estabelecimento = campos[2].strip()

            elif reg == 'C100':
                # Layout C100 (posições 1-indexed após split por |):
                # 1=REG 2=IND_OPER 3=IND_EMIT 4=COD_PART 5=COD_MOD 6=COD_SIT
                # 7=SER 8=NUM_DOC 9=CHV_NFE 10=DT_DOC 11=DT_ENT_SAI 12=VL_DOC
                # 13=IND_PGTO 14=VL_DESC 15=VL_ABAT_NT 16=VL_MERC 17=IND_FRT
                # 18=VL_FRT 19=VL_SEG 20=VL_OUT_DA 21=VL_BC_ICMS 22=VL_ICMS
                # 23=VL_BC_ICMS_ST 24=VL_ICMS_ST 25=VL_IPI 26=VL_PIS 27=VL_COFINS
                # 28=VL_PIS_ST 29=VL_COFINS_ST
                ind_emit = campos[3].strip()
                cod_part = campos[4].strip()
                part = participantes.get(cod_part, {})
                doc_part = part.get('cnpj') or part.get('cpf', '')

                if ind_emit == '0':
                    cnpj_emit = cnpj_estabelecimento
                    cnpj_dest = doc_part
                else:
                    cnpj_emit = doc_part
                    cnpj_dest = cnpj_estabelecimento

                num_doc = campos[8].strip()
                nota_atual = num_doc
                notas[nota_atual] = {
                    'tipo_bloco': 'C100',
                    'ind_oper': campos[2].strip(),
                    'ind_emit': ind_emit,
                    'cod_part': cod_part,
                    'nome_part': part.get('nome', ''),
                    'cnpj_emit': cnpj_emit,
                    'cnpj_dest': cnpj_dest,
                    'cod_mod': campos[5].strip(),
                    'cod_sit': campos[6].strip(),
                    'serie': campos[7].strip(),
                    'num_doc': num_doc,
                    'chv_nfe': campos[9].strip() if len(campos) > 9 else '',
                    'dt_doc': campos[10].strip() if len(campos) > 10 else '',
                    'dt_ent_sai': campos[11].strip() if len(campos) > 11 else '',
                    'vl_doc': _to_float(campos[12]) if len(campos) > 12 else 0.0,
                    'vl_desc': _to_float(campos[14]) if len(campos) > 14 else 0.0,
                    'vl_merc': _to_float(campos[16]) if len(campos) > 16 else 0.0,
                    'vl_frt': _to_float(campos[18]) if len(campos) > 18 else 0.0,
                    'vl_seg': _to_float(campos[19]) if len(campos) > 19 else 0.0,
                    'vl_out_da': _to_float(campos[20]) if len(campos) > 20 else 0.0,
                    'vl_bc_icms': _to_float(campos[21]) if len(campos) > 21 else 0.0,
                    'vl_icms': _to_float(campos[22]) if len(campos) > 22 else 0.0,
                    'vl_bc_icms_st': _to_float(campos[23]) if len(campos) > 23 else 0.0,
                    'vl_icms_st': _to_float(campos[24]) if len(campos) > 24 else 0.0,
                    'vl_ipi': _to_float(campos[25]) if len(campos) > 25 else 0.0,
                    'vl_pis': _to_float(campos[26]) if len(campos) > 26 else 0.0,
                    'vl_cofins': _to_float(campos[27]) if len(campos) > 27 else 0.0,
                    'itens': [],
                }

            elif reg == 'C170' and nota_atual is not None:
                # Layout C170 (posições 1-indexed após split por |):
                # 1=REG 2=NUM_ITEM 3=COD_ITEM 4=DESCR_COMPL 5=QTD 6=UNID
                # 7=VL_ITEM 8=VL_DESC 9=IND_MOV 10=CST_ICMS 11=CFOP 12=COD_NAT
                # 13=VL_BC_ICMS 14=ALIQ_ICMS 15=VL_ICMS 16=VL_BC_ICMS_ST
                # 17=ALIQ_ST 18=VL_ICMS_ST 19=IND_APUR 20=CST_PIS
                # 26=VL_BC_PIS 27=ALIQ_PIS_PERC 28=QUANT_BC_PIS
                # 29=ALIQ_PIS_REAIS 30=VL_PIS 31=CST_COFINS 32=VL_BC_COFINS
                # 33=ALIQ_COFINS_PERC 34=QUANT_BC_COFINS 35=ALIQ_COFINS_REAIS
                # 36=VL_COFINS 37=COD_CTA
                item = {
                    'num_item': campos[2].strip(),
                    'cod_item': campos[3].strip(),
                    'descr': campos[4].strip(),
                    'qtd': _to_float(campos[5]),
                    'unid': campos[6].strip(),
                    'vl_item': _to_float(campos[7]),
                    'cfop': campos[11].strip(),
                    'cst_icms': campos[10].strip() if len(campos) > 10 else '',
                    'vl_bc_icms': _to_float(campos[13]) if len(campos) > 13 else 0.0,
                    'aliq_icms': _to_float(campos[14]) if len(campos) > 14 else 0.0,
                    'vl_icms': _to_float(campos[15]) if len(campos) > 15 else 0.0,
                    'vl_bc_icms_st': _to_float(campos[16]) if len(campos) > 16 else 0.0,
                    'aliq_st': _to_float(campos[17]) if len(campos) > 17 else 0.0,
                    'vl_icms_st': _to_float(campos[18]) if len(campos) > 18 else 0.0,
                    'cst_pis': campos[20].strip() if len(campos) > 20 else '',
                    'vl_bc_pis': _to_float(campos[26]) if len(campos) > 26 else 0.0,
                    'aliq_pis': _to_float(campos[27]) if len(campos) > 27 else 0.0,
                    'vl_pis': _to_float(campos[30]) if len(campos) > 30 else 0.0,
                    'cst_cofins': campos[31].strip() if len(campos) > 31 else '',
                    'vl_bc_cofins': _to_float(campos[32]) if len(campos) > 32 else 0.0,
                    'aliq_cofins': _to_float(campos[33]) if len(campos) > 33 else 0.0,
                    'vl_cofins': _to_float(campos[36]) if len(campos) > 36 else 0.0,
                    'cod_cta': campos[37].strip() if len(campos) > 37 else '',
                }
                notas[nota_atual]['itens'].append(item)

            elif reg == 'C500':
                # Layout C500 (posições 1-indexed após split por |):
                # 1=REG 2=COD_PART 3=COD_MOD 4=COD_SIT 5=SER 6=SUB
                # 7=NUM_DOC 8=DT_DOC 9=DT_ENT_SAI 10=VL_DOC 11=VL_DESC
                # 12=VL_BC_ICMS 13=VL_PIS 14=VL_COFINS 15=VL_PIS_ST
                cod_part = campos[2].strip()
                part = participantes.get(cod_part, {})
                doc_part = part.get('cnpj') or part.get('cpf', '')

                num_doc = campos[7].strip()
                nota_atual = num_doc
                notas[nota_atual] = {
                    'tipo_bloco': 'C500',
                    'cod_part': cod_part,
                    'nome_part': part.get('nome', ''),
                    'cnpj_emit': doc_part,
                    'cnpj_dest': cnpj_estabelecimento,
                    'cod_mod': campos[3].strip(),
                    'cod_sit': campos[4].strip(),
                    'serie': campos[5].strip(),
                    'num_doc': num_doc,
                    'dt_doc': campos[8].strip() if len(campos) > 8 else '',
                    'dt_ent_sai': campos[9].strip() if len(campos) > 9 else '',
                    'vl_doc': _to_float(campos[10]) if len(campos) > 10 else 0.0,
                    'vl_pis': _to_float(campos[13]) if len(campos) > 13 else 0.0,
                    'vl_cofins': _to_float(campos[14]) if len(campos) > 14 else 0.0,
                    'itens': [],
                }

            elif reg == 'C501' and nota_atual is not None:
                # Layout C501 (PIS da nota de energia/serviços):
                # 1=REG 2=CST_PIS 3=VL_TOT_REC 4=ALIQ_PIS_PERC 5=QUANT_BC_PIS
                # 6=ALIQ_PIS_REAIS 7=VL_PIS 8=COD_CTA
                item = {
                    'tipo': 'pis',
                    'cst': campos[2].strip(),
                    'vl_bc': _to_float(campos[3]),
                    'aliq_perc': _to_float(campos[4]),
                    'quant_bc': _to_float(campos[5]),
                    'aliq_reais': _to_float(campos[6]),
                    'vl': _to_float(campos[7]),
                    'cod_cta': campos[8].strip() if len(campos) > 8 else '',
                }
                notas[nota_atual]['itens'].append(item)

            elif reg == 'C505' and nota_atual is not None:
                # Layout C505 (COFINS da nota de energia/serviços):
                # 1=REG 2=CST_COFINS 3=VL_TOT_REC 4=ALIQ_COFINS_PERC
                # 5=QUANT_BC_COFINS 6=ALIQ_COFINS_REAIS 7=VL_COFINS 8=COD_CTA
                item = {
                    'tipo': 'cofins',
                    'cst': campos[2].strip(),
                    'vl_bc': _to_float(campos[3]),
                    'aliq_perc': _to_float(campos[4]),
                    'quant_bc': _to_float(campos[5]),
                    'aliq_reais': _to_float(campos[6]),
                    'vl': _to_float(campos[7]),
                    'cod_cta': campos[8].strip() if len(campos) > 8 else '',
                }
                notas[nota_atual]['itens'].append(item)

    return notas


# ── Exemplo de uso ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import json

    arquivo = 'arquivos_auxiliares/arquivos_base/2 - Sped Contribuicoes.txt'
    dados = extrair_por_nota(arquivo)

    primeiros = dict(list(dados.items())[:2])
    print(json.dumps(primeiros, ensure_ascii=False, indent=2, default=str))

    print(f'\nTotal de notas extraídas: {len(dados)}')

    """
    Lê o arquivo SPED Contribuições (.txt) e retorna um dicionário onde cada
    chave é o número do documento e o valor contém os dados da nota e seus itens.

    Cobre os blocos C100/C170 (NF-e, NF modelo 55) e C500/C501/C505 (energia
    elétrica, modelo 06/21).

    O CNPJ do emitente e do destinatário é resolvido a partir de:
      - Registro 0150: tabela de participantes (cod_part → nome/cnpj/cpf)
      - Registro C010: CNPJ do estabelecimento emitente do bloco C

    Regra:
      ind_emit='0' (emissão própria) → cnpj_emit = estabelecimento (C010),
                                       cnpj_dest = participante (0150)
      ind_emit='1' (terceiros)       → cnpj_emit = participante (0150),
                                       cnpj_dest = estabelecimento (C010)

    Retorno:
        {
            "38676": {
                "tipo_bloco": "C100",
                "ind_oper": "0",
                "ind_emit": "0",
                "cod_part": "C00181",
                "nome_part": "JOAO LOPES FERREIRA JUNIOR",
                "cnpj_emit": "04784935000167",
                "cnpj_dest": "84803061149",
                "cod_mod": "55",
                "cod_sit": "00",
                "serie": "001",
                "num_doc": "38676",
                "chv_nfe": "52260304784935000167550010000386761931016647",
                "dt_doc": "04032026",
                "dt_ent_sai": "04032026",
                "vl_doc": 251.68,
                "vl_desc": 0.0,
                "vl_merc": 251.68,
                "vl_frt": 0.0,
                "vl_seg": 0.0,
                "vl_out_da": 0.0,
                "vl_bc_icms": 251.68,
                "vl_icms": 47.82,
                "vl_bc_icms_st": 0.0,
                "vl_icms_st": 0.0,
                "vl_ipi": 0.0,
                "vl_pis": 0.0,
                "vl_cofins": 0.0,
                "itens": [
                    {
                        "num_item": "1",
                        "cod_item": "R002469",
                        "descr": "FITA ISOLANTE AUTOFUSAO 19MM X 10M Prysmian",
                        "qtd": 4.0,
                        "unid": "UN",
                        "vl_item": 103.24,
                        "cfop": "1949",
                        "cst_icms": "000",
                        "vl_bc_icms": 103.24,
                        "aliq_icms": 19.0,
                        "vl_icms": 19.62,
                        "vl_bc_icms_st": 0.0,
                        "aliq_st": 0.0,
                        "vl_icms_st": 0.0,
                        "cst_pis": "49",
                        "vl_bc_pis": 0.0,
                        "aliq_pis": 0.0,
                        "vl_pis": 0.0,
                        "cst_cofins": "98",
                        "vl_bc_cofins": 0.0,
                        "aliq_cofins": 0.0,
                        "vl_cofins": 0.0,
                        "cod_cta": "4.01.03.01.0003"
                    }
                ]
            }
        }
    """
