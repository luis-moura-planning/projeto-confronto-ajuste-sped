import math
import pandas as pd
from services.extrai_dados_sped import extrai_dados_sped
from services.extrai_dados_planilha_sap import extrai_dados_planilha_sap


def _clean(v):
    """Converte NaN/float-inf para string vazia, evitando erros de serialização JSON."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return ''
    return v


df_contas = pd.DataFrame({
    "descricao_conta": [
        "PIS a Recuperar",
        "COFINS a Recuperar",
        "PIS a Recolher",
        "COFINS a Recolher",
        "( - ) PIS/PASEP",
        "( - ) COFINS",
        "(-) PIS s/ Receitas Financeiras",
        "(-) COFINS s/ Receitas Financeiras",
        "(-) Pis s/ Alugués",
        "(-) Cofins s/ Aluguéis",
        "(-) Pis s/ Energia",
        "(-) Cofins s/ Energia",
        "(-) Pis s/ Depreciação",
        "(-) Cofins s/ Depreciação",
    ],
    "codigo_conta": [
        "1.01.05.01.0003",
        "1.01.05.01.0004",
        "2.01.01.04.0002",
        "2.01.01.04.0003",
        "3.01.01.03.0003",
        "3.01.01.03.0004",
        "3.03.01.01.0006",
        "3.03.01.01.0007",
        "4.01.02.03.0011",
        "4.01.02.03.0012",
        "5.01.01.04.0029",
        "5.01.01.04.0030",
        "5.01.01.06.0003",
        "5.01.01.06.0004",
    ]
})


def _parse_valor(v):
    if pd.isna(v) or v == '':
        return None
    s = str(v).strip().replace('R$', '').strip()
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    return float(s)


def comparacao_valores(valor_sap, valor_sped):
    valor_sap = _parse_valor(valor_sap)
    valor_sped = _parse_valor(valor_sped)

    sap_vazio = valor_sap is None
    sped_vazio = valor_sped is None

    if sped_vazio and not sap_vazio:
        return 0, "apenas_sap"
    elif sap_vazio and not sped_vazio:
        return 0, "apenas_sped"
    elif sap_vazio and sped_vazio:
        return 0, "sem_valor"
    elif valor_sped > valor_sap:
        return valor_sped - valor_sap, "complemento"
    elif valor_sap > valor_sped:
        return valor_sap - valor_sped, "estorno"
    else:
        return 0, "ok"


def gerar_lancamento(bloco='',codigo_conta='', descricao_conta='', debito='', credito='', descricao='', centro_de_custo='', filial=''):
    return {
        'bloco': bloco,
        'codigo_da_conta': codigo_conta,
        'descricao_conta': descricao_conta,
        'debito':  _parse_valor(debito),
        'credito': _parse_valor(credito),
        'descricao': descricao,
        'centro_de_custo': centro_de_custo,
        'filial': filial,
    }


def gerar_registro(bloco='', num_doc='', identificador='', imposto='', vl_sped='', vl_sap='', status=''):
    return {
        'bloco': bloco,
        'num_doc': num_doc,
        'identificador': identificador,
        'imposto': imposto,
        'vl_sped': _parse_valor(vl_sped),
        'vl_sap':  _parse_valor(vl_sap),
        'status': status,
    }


def compara_gera_diferenca(planilha_sap_path, sped_path):
    df_sap  = extrai_dados_planilha_sap(planilha_sap_path)
    df_sped = extrai_dados_sped(sped_path)

    df_bloco_0000 = df_sped['0000']
    df_bloco_a100 = df_sped['A100']
    df_bloco_c100 = df_sped['C100']
    df_bloco_c501 = df_sped['C501']
    df_bloco_c505 = df_sped['C505']
    df_bloco_d101 = df_sped['D101']
    df_bloco_d105 = df_sped['D105']
    df_bloco_f100 = df_sped['F100']
    df_bloco_f120 = df_sped['F120']
    df_bloco_M110 = df_sped['M110']
    df_bloco_M215 = df_sped['M215']
    df_bloco_M510 = df_sped['M510']
    df_bloco_M615 = df_sped['M615']

    lancamentos = []
    registros   = []

    def _validar_a100():
        if df_bloco_a100.empty:
            return

        sap_pis    = df_sap[df_sap['Imposto'] == 'PIS']
        sap_cofins = df_sap[df_sap['Imposto'] == 'COFINS']

        for _, registro in df_bloco_a100.iterrows():
            num_doc        = registro.get('NUM_DOC', '')
            chv_nfse       = registro.get('CHV_NFSE', '')
            ind_oper       = registro.get('IND_OPER', '')
            vl_pis_sped    = registro.get('VL_PIS', '')
            vl_cofins_sped = registro.get('VL_COFINS', '')
            filial         = registro.get('CNPJ_ESTAB', '')
            descricao      = f"A100 - {num_doc}"

            if ind_oper == '0':
                cta_pis_deb,  desc_pis_deb  = '1.01.05.01.0003', 'PIS a Recuperar'
                cta_pis_cred, desc_pis_cred = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_cof_deb,  desc_cof_deb  = '1.01.05.01.0004', 'COFINS a Recuperar'
                cta_cof_cred, desc_cof_cred = '3.01.01.03.0004', '( - ) COFINS'
            else:
                cta_pis_deb,  desc_pis_deb  = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_pis_cred, desc_pis_cred = '2.01.01.04.0002', 'PIS a Recolher'
                cta_cof_deb,  desc_cof_deb  = '3.01.01.03.0004', '( - ) COFINS'
                cta_cof_cred, desc_cof_cred = '2.01.01.04.0003', 'COFINS a Recolher'

            # --- PIS ---
            match_pis = sap_pis[sap_pis['Ref.3 (Linha)'] == num_doc]
            if match_pis.empty:
                match_pis = sap_pis[sap_pis['Valor'].apply(_parse_valor) == _parse_valor(vl_pis_sped)]
            if not match_pis.empty:
                vl_sap_pis            = match_pis.iloc[0]['Valor']
                delta_pis, status_pis = comparacao_valores(vl_sap_pis, vl_pis_sped)
                cc_pis                = match_pis.iloc[0].get('Centro de Custo', '')
            else:
                vl_sap_pis = ''
                delta_pis  = _parse_valor(vl_pis_sped) or 0
                status_pis = 'so_sped'
                cc_pis     = ''

            registros.append(gerar_registro(
                bloco="A100", num_doc=num_doc, identificador=chv_nfse,
                imposto="PIS", vl_sped=vl_pis_sped, vl_sap=vl_sap_pis, status=status_pis
            ))

            if status_pis in ('so_sped', 'complemento', 'estorno'):
                deb_pis   = cta_pis_deb  if status_pis != 'estorno' else cta_pis_cred
                ddesc_pis = desc_pis_deb if status_pis != 'estorno' else desc_pis_cred
                cred_pis  = cta_pis_cred if status_pis != 'estorno' else cta_pis_deb
                cdesc_pis = desc_pis_cred if status_pis != 'estorno' else desc_pis_deb
                lancamentos.append(gerar_lancamento(
                    bloco="A100", codigo_conta=deb_pis, descricao_conta=ddesc_pis,
                    debito=delta_pis, credito='',
                    descricao=descricao, centro_de_custo=cc_pis, filial=filial
                ))
                lancamentos.append(gerar_lancamento(
                    bloco="A100", codigo_conta=cred_pis, descricao_conta=cdesc_pis,
                    debito='', credito=delta_pis,
                    descricao=descricao, centro_de_custo=cc_pis, filial=filial
                ))

            # --- COFINS ---
            match_cofins = sap_cofins[sap_cofins['Ref.3 (Linha)'] == num_doc]
            if match_cofins.empty:
                match_cofins = sap_cofins[sap_cofins['Valor'].apply(_parse_valor) == _parse_valor(vl_cofins_sped)]
            if not match_cofins.empty:
                vl_sap_cofins               = match_cofins.iloc[0]['Valor']
                delta_cofins, status_cofins = comparacao_valores(vl_sap_cofins, vl_cofins_sped)
                cc_cofins                   = match_cofins.iloc[0].get('Centro de Custo', '')
            else:
                vl_sap_cofins = ''
                delta_cofins  = _parse_valor(vl_cofins_sped) or 0
                status_cofins = 'so_sped'
                cc_cofins     = ''

            registros.append(gerar_registro(
                bloco="A100", num_doc=num_doc, identificador=chv_nfse,
                imposto="COFINS", vl_sped=vl_cofins_sped, vl_sap=vl_sap_cofins, status=status_cofins
            ))

            if status_cofins in ('so_sped', 'complemento', 'estorno'):
                deb_cof   = cta_cof_deb  if status_cofins != 'estorno' else cta_cof_cred
                ddesc_cof = desc_cof_deb if status_cofins != 'estorno' else desc_cof_cred
                cred_cof  = cta_cof_cred if status_cofins != 'estorno' else cta_cof_deb
                cdesc_cof = desc_cof_cred if status_cofins != 'estorno' else desc_cof_deb
                lancamentos.append(gerar_lancamento(
                    bloco="A100", codigo_conta=deb_cof, descricao_conta=ddesc_cof,
                    debito=delta_cofins, credito='',
                    descricao=descricao, centro_de_custo=cc_cofins, filial=filial
                ))
                lancamentos.append(gerar_lancamento(
                    bloco="A100", codigo_conta=cred_cof, descricao_conta=cdesc_cof,
                    debito='', credito=delta_cofins,
                    descricao=descricao, centro_de_custo=cc_cofins, filial=filial
                ))

    def _validar_c100():
        if df_bloco_c100.empty:
            return

        sap_pis    = df_sap[df_sap['Imposto'] == 'PIS']
        sap_cofins = df_sap[df_sap['Imposto'] == 'COFINS']

        for _, registro in df_bloco_c100.iterrows():
            num_doc        = registro.get('NUM_DOC', '')
            chv_nfe        = registro.get('CHV_NFE', '')
            ind_oper       = registro.get('IND_OPER', '')
            vl_pis_sped    = registro.get('VL_PIS', '')
            vl_cofins_sped = registro.get('VL_COFINS', '')
            filial         = registro.get('CNPJ_ESTAB', '')
            descricao      = f"C100 - {num_doc}"

            if not _parse_valor(vl_pis_sped) and not _parse_valor(vl_cofins_sped):
                continue

            if ind_oper == '0':
                cta_pis_deb,  desc_pis_deb  = '1.01.05.01.0003', 'PIS a Recuperar'
                cta_pis_cred, desc_pis_cred = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_cof_deb,  desc_cof_deb  = '1.01.05.01.0004', 'COFINS a Recuperar'
                cta_cof_cred, desc_cof_cred = '3.01.01.03.0004', '( - ) COFINS'
            else:
                cta_pis_deb,  desc_pis_deb  = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_pis_cred, desc_pis_cred = '2.01.01.04.0002', 'PIS a Recolher'
                cta_cof_deb,  desc_cof_deb  = '3.01.01.03.0004', '( - ) COFINS'
                cta_cof_cred, desc_cof_cred = '2.01.01.04.0003', 'COFINS a Recolher'

            # --- PIS ---
            match_pis = sap_pis[sap_pis['Ref.3 (Linha)'] == num_doc]
            if match_pis.empty:
                match_pis = sap_pis[sap_pis['Valor'].apply(_parse_valor) == _parse_valor(vl_pis_sped)]
            if not match_pis.empty:
                vl_sap_pis            = match_pis.iloc[0]['Valor']
                delta_pis, status_pis = comparacao_valores(vl_sap_pis, vl_pis_sped)
                cc_pis                = match_pis.iloc[0].get('Centro de Custo', '')
            else:
                vl_sap_pis = ''
                delta_pis  = _parse_valor(vl_pis_sped) or 0
                status_pis = 'so_sped'
                cc_pis     = ''

            registros.append(gerar_registro(
                bloco="C100", num_doc=num_doc, identificador=chv_nfe,
                imposto="PIS", vl_sped=vl_pis_sped, vl_sap=vl_sap_pis, status=status_pis
            ))

            if status_pis in ('so_sped', 'complemento', 'estorno'):
                deb_pis   = cta_pis_deb  if status_pis != 'estorno' else cta_pis_cred
                ddesc_pis = desc_pis_deb if status_pis != 'estorno' else desc_pis_cred
                cred_pis  = cta_pis_cred if status_pis != 'estorno' else cta_pis_deb
                cdesc_pis = desc_pis_cred if status_pis != 'estorno' else desc_pis_deb
                lancamentos.append(gerar_lancamento(
                    bloco="C100", codigo_conta=deb_pis, descricao_conta=ddesc_pis,
                    debito=delta_pis, credito='',
                    descricao=descricao, centro_de_custo=cc_pis, filial=filial
                ))
                lancamentos.append(gerar_lancamento(
                    bloco="C100", codigo_conta=cred_pis, descricao_conta=cdesc_pis,
                    debito='', credito=delta_pis,
                    descricao=descricao, centro_de_custo=cc_pis, filial=filial
                ))

            # --- COFINS ---
            match_cofins = sap_cofins[sap_cofins['Ref.3 (Linha)'] == num_doc]
            if match_cofins.empty:
                match_cofins = sap_cofins[sap_cofins['Valor'].apply(_parse_valor) == _parse_valor(vl_cofins_sped)]
            if not match_cofins.empty:
                vl_sap_cofins               = match_cofins.iloc[0]['Valor']
                delta_cofins, status_cofins = comparacao_valores(vl_sap_cofins, vl_cofins_sped)
                cc_cofins                   = match_cofins.iloc[0].get('Centro de Custo', '')
            else:
                vl_sap_cofins = ''
                delta_cofins  = _parse_valor(vl_cofins_sped) or 0
                status_cofins = 'so_sped'
                cc_cofins     = ''

            registros.append(gerar_registro(
                bloco="C100", num_doc=num_doc, identificador=chv_nfe,
                imposto="COFINS", vl_sped=vl_cofins_sped, vl_sap=vl_sap_cofins, status=status_cofins
            ))

            if status_cofins in ('so_sped', 'complemento', 'estorno'):
                deb_cof   = cta_cof_deb  if status_cofins != 'estorno' else cta_cof_cred
                ddesc_cof = desc_cof_deb if status_cofins != 'estorno' else desc_cof_cred
                cred_cof  = cta_cof_cred if status_cofins != 'estorno' else cta_cof_deb
                cdesc_cof = desc_cof_cred if status_cofins != 'estorno' else desc_cof_deb
                lancamentos.append(gerar_lancamento(
                    bloco="C100", codigo_conta=deb_cof, descricao_conta=ddesc_cof,
                    debito=delta_cofins, credito='',
                    descricao=descricao, centro_de_custo=cc_cofins, filial=filial
                ))
                lancamentos.append(gerar_lancamento(
                    bloco="C100", codigo_conta=cred_cof, descricao_conta=cdesc_cof,
                    debito='', credito=delta_cofins,
                    descricao=descricao, centro_de_custo=cc_cofins, filial=filial
                ))

    def _validar_c501():
        if df_bloco_c501.empty:
            return

        sap_pis = df_sap[df_sap['Imposto'] == 'PIS']

        for _, registro in df_bloco_c501.iterrows():
            num_doc     = registro.get('NUM_DOC', '')
            chv_doce    = registro.get('CHV_DOCe', '')
            ind_oper    = registro.get('IND_OPER', '0')
            vl_pis_sped = registro.get('VL_PIS', '')
            filial      = registro.get('CNPJ_ESTAB', '')
            descricao   = f"C501 - {num_doc}"

            if not _parse_valor(vl_pis_sped):
                continue

            if ind_oper == '0':
                cta_deb,  desc_deb  = '1.01.05.01.0003', 'PIS a Recuperar'
                cta_cred, desc_cred = '3.01.01.03.0003', '( - ) PIS/PASEP'
            else:
                cta_deb,  desc_deb  = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_cred, desc_cred = '2.01.01.04.0002', 'PIS a Recolher'

            match = sap_pis[sap_pis['Ref.3 (Linha)'] == num_doc]
            if match.empty:
                match = sap_pis[sap_pis['Valor'].apply(_parse_valor) == _parse_valor(vl_pis_sped)]

            if not match.empty:
                vl_sap        = match.iloc[0]['Valor']
                delta, status = comparacao_valores(vl_sap, vl_pis_sped)
                cc            = match.iloc[0].get('Centro de Custo', '')
            else:
                vl_sap  = ''
                delta   = _parse_valor(vl_pis_sped) or 0
                status  = 'so_sped'
                cc      = ''

            registros.append(gerar_registro(
                bloco="C501", num_doc=num_doc, identificador=chv_doce,
                imposto="PIS", vl_sped=vl_pis_sped, vl_sap=vl_sap, status=status
            ))

            if status in ('so_sped', 'complemento', 'estorno'):
                d  = cta_deb  if status != 'estorno' else cta_cred
                dd = desc_deb if status != 'estorno' else desc_cred
                c  = cta_cred if status != 'estorno' else cta_deb
                cd = desc_cred if status != 'estorno' else desc_deb
                lancamentos.append(gerar_lancamento(
                    bloco="C501", codigo_conta=d, descricao_conta=dd,
                    debito=delta, credito='',
                    descricao=descricao, centro_de_custo=cc, filial=filial
                ))
                lancamentos.append(gerar_lancamento(
                    bloco="C501", codigo_conta=c, descricao_conta=cd,
                    debito='', credito=delta,
                    descricao=descricao, centro_de_custo=cc, filial=filial
                ))

    def _validar_c505():
        if df_bloco_c505.empty:
            return

        sap_cofins = df_sap[df_sap['Imposto'] == 'COFINS']

        for _, registro in df_bloco_c505.iterrows():
            num_doc        = registro.get('NUM_DOC', '')
            chv_doce       = registro.get('CHV_DOCe', '')
            ind_oper       = registro.get('IND_OPER', '0')
            vl_cofins_sped = registro.get('VL_COFINS', '')
            filial         = registro.get('CNPJ_ESTAB', '')
            descricao      = f"C505 - {num_doc}"

            if not _parse_valor(vl_cofins_sped):
                continue

            if ind_oper == '0':
                cta_deb,  desc_deb  = '1.01.05.01.0004', 'COFINS a Recuperar'
                cta_cred, desc_cred = '3.01.01.03.0004', '( - ) COFINS'
            else:
                cta_deb,  desc_deb  = '3.01.01.03.0004', '( - ) COFINS'
                cta_cred, desc_cred = '2.01.01.04.0003', 'COFINS a Recolher'

            match = sap_cofins[sap_cofins['Ref.3 (Linha)'] == num_doc]
            if match.empty:
                match = sap_cofins[sap_cofins['Valor'].apply(_parse_valor) == _parse_valor(vl_cofins_sped)]

            if not match.empty:
                vl_sap        = match.iloc[0]['Valor']
                delta, status = comparacao_valores(vl_sap, vl_cofins_sped)
                cc            = match.iloc[0].get('Centro de Custo', '')
            else:
                vl_sap  = ''
                delta   = _parse_valor(vl_cofins_sped) or 0
                status  = 'so_sped'
                cc      = ''

            registros.append(gerar_registro(
                bloco="C505", num_doc=num_doc, identificador=chv_doce,
                imposto="COFINS", vl_sped=vl_cofins_sped, vl_sap=vl_sap, status=status
            ))

            if status in ('so_sped', 'complemento', 'estorno'):
                d  = cta_deb  if status != 'estorno' else cta_cred
                dd = desc_deb if status != 'estorno' else desc_cred
                c  = cta_cred if status != 'estorno' else cta_deb
                cd = desc_cred if status != 'estorno' else desc_deb
                lancamentos.append(gerar_lancamento(
                    bloco="C505", codigo_conta=d, descricao_conta=dd,
                    debito=delta, credito='',
                    descricao=descricao, centro_de_custo=cc, filial=filial
                ))
                lancamentos.append(gerar_lancamento(
                    bloco="C505", codigo_conta=c, descricao_conta=cd,
                    debito='', credito=delta,
                    descricao=descricao, centro_de_custo=cc, filial=filial
                ))

    def _validar_d101():
        if df_bloco_d101.empty:
            return

        sap_pis = df_sap[df_sap['Imposto'] == 'PIS']

        for _, registro in df_bloco_d101.iterrows():
            num_doc     = registro.get('NUM_DOC', '')
            chv_cte     = registro.get('CHV_CTE', '')
            ind_oper    = registro.get('IND_OPER', '0')
            vl_pis_sped = registro.get('VL_PIS', '')
            filial      = registro.get('CNPJ_ESTAB', '')
            descricao   = f"D101 - {num_doc}"

            if not _parse_valor(vl_pis_sped):
                continue

            if ind_oper == '0':
                cta_deb,  desc_deb  = '1.01.05.01.0003', 'PIS a Recuperar'
                cta_cred, desc_cred = '3.01.01.03.0003', '( - ) PIS/PASEP'
            else:
                cta_deb,  desc_deb  = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_cred, desc_cred = '2.01.01.04.0002', 'PIS a Recolher'

            match = sap_pis[sap_pis['Ref.3 (Linha)'] == num_doc]
            if match.empty:
                match = sap_pis[sap_pis['Valor'].apply(_parse_valor) == _parse_valor(vl_pis_sped)]

            if not match.empty:
                vl_sap       = match.iloc[0]['Valor']
                delta, status = comparacao_valores(vl_sap, vl_pis_sped)
                cc            = match.iloc[0].get('Centro de Custo', '')
            else:
                vl_sap  = ''
                delta   = _parse_valor(vl_pis_sped) or 0
                status  = 'so_sped'
                cc      = ''

            registros.append(gerar_registro(
                bloco="D101", num_doc=num_doc, identificador=chv_cte,
                imposto="PIS", vl_sped=vl_pis_sped, vl_sap=vl_sap, status=status
            ))

            if status in ('so_sped', 'complemento', 'estorno'):
                d = cta_deb  if status != 'estorno' else cta_cred
                dd = desc_deb if status != 'estorno' else desc_cred
                c = cta_cred if status != 'estorno' else cta_deb
                cd = desc_cred if status != 'estorno' else desc_deb
                lancamentos.append(gerar_lancamento(
                    bloco="D101", codigo_conta=d, descricao_conta=dd,
                    debito=delta, credito='',
                    descricao=descricao, centro_de_custo=cc, filial=filial
                ))
                lancamentos.append(gerar_lancamento(
                    bloco="D101", codigo_conta=c, descricao_conta=cd,
                    debito='', credito=delta,
                    descricao=descricao, centro_de_custo=cc, filial=filial
                ))

    def _validar_d105():
        if df_bloco_d105.empty:
            return

        sap_cofins = df_sap[df_sap['Imposto'] == 'COFINS']

        for _, registro in df_bloco_d105.iterrows():
            num_doc        = registro.get('NUM_DOC', '')
            chv_cte        = registro.get('CHV_CTE', '')
            ind_oper       = registro.get('IND_OPER', '0')
            vl_cofins_sped = registro.get('VL_COFINS', '')
            filial         = registro.get('CNPJ_ESTAB', '')
            descricao      = f"D105 - {num_doc}"

            if not _parse_valor(vl_cofins_sped):
                continue

            if ind_oper == '0':
                cta_deb,  desc_deb  = '1.01.05.01.0004', 'COFINS a Recuperar'
                cta_cred, desc_cred = '3.01.01.03.0004', '( - ) COFINS'
            else:
                cta_deb,  desc_deb  = '3.01.01.03.0004', '( - ) COFINS'
                cta_cred, desc_cred = '2.01.01.04.0003', 'COFINS a Recolher'

            match = sap_cofins[sap_cofins['Ref.3 (Linha)'] == num_doc]
            if match.empty:
                match = sap_cofins[sap_cofins['Valor'].apply(_parse_valor) == _parse_valor(vl_cofins_sped)]

            if not match.empty:
                vl_sap        = match.iloc[0]['Valor']
                delta, status = comparacao_valores(vl_sap, vl_cofins_sped)
                cc            = match.iloc[0].get('Centro de Custo', '')
            else:
                vl_sap  = ''
                delta   = _parse_valor(vl_cofins_sped) or 0
                status  = 'so_sped'
                cc      = ''

            registros.append(gerar_registro(
                bloco="D105", num_doc=num_doc, identificador=chv_cte,
                imposto="COFINS", vl_sped=vl_cofins_sped, vl_sap=vl_sap, status=status
            ))

            if status in ('so_sped', 'complemento', 'estorno'):
                d = cta_deb  if status != 'estorno' else cta_cred
                dd = desc_deb if status != 'estorno' else desc_cred
                c = cta_cred if status != 'estorno' else cta_deb
                cd = desc_cred if status != 'estorno' else desc_deb
                lancamentos.append(gerar_lancamento(
                    bloco="D105", codigo_conta=d, descricao_conta=dd,
                    debito=delta, credito='',
                    descricao=descricao, centro_de_custo=cc, filial=filial
                ))
                lancamentos.append(gerar_lancamento(
                    bloco="D105", codigo_conta=c, descricao_conta=cd,
                    debito='', credito=delta,
                    descricao=descricao, centro_de_custo=cc, filial=filial
                ))

    def _validar_f100():
        if df_bloco_f100.empty:
            return

        sap_pis    = df_sap[df_sap['Imposto'] == 'PIS']
        sap_cofins = df_sap[df_sap['Imposto'] == 'COFINS']

        for _, registro in df_bloco_f100.iterrows():
            desc           = registro.get('DESC_DOC_OPER', '')
            ind_oper       = registro.get('IND_OPER', '0')
            vl_pis_sped    = registro.get('VL_PIS', '')
            vl_cofins_sped = registro.get('VL_COFINS', '')
            filial         = registro.get('CNPJ_ESTAB', '')
            descricao      = f"F100 - {desc}"

            if ind_oper == '0':
                cta_pis_deb,  desc_pis_deb  = '1.01.05.01.0003', 'PIS a Recuperar'
                cta_pis_cred, desc_pis_cred = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_cof_deb,  desc_cof_deb  = '1.01.05.01.0004', 'COFINS a Recuperar'
                cta_cof_cred, desc_cof_cred = '3.01.01.03.0004', '( - ) COFINS'
            else:
                cta_pis_deb,  desc_pis_deb  = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_pis_cred, desc_pis_cred = '2.01.01.04.0002', 'PIS a Recolher'
                cta_cof_deb,  desc_cof_deb  = '3.01.01.03.0004', '( - ) COFINS'
                cta_cof_cred, desc_cof_cred = '2.01.01.04.0003', 'COFINS a Recolher'

            # --- PIS ---
            if _parse_valor(vl_pis_sped):
                match_pis = sap_pis[sap_pis['Valor'].apply(_parse_valor) == _parse_valor(vl_pis_sped)]
                if not match_pis.empty:
                    vl_sap_pis            = match_pis.iloc[0]['Valor']
                    delta_pis, status_pis = comparacao_valores(vl_sap_pis, vl_pis_sped)
                    cc_pis                = match_pis.iloc[0].get('Centro de Custo', '')
                else:
                    vl_sap_pis = ''
                    delta_pis  = _parse_valor(vl_pis_sped) or 0
                    status_pis = 'so_sped'
                    cc_pis     = ''

                registros.append(gerar_registro(
                    bloco="F100", num_doc=desc, identificador=desc,
                    imposto="PIS", vl_sped=vl_pis_sped, vl_sap=vl_sap_pis, status=status_pis
                ))

                if status_pis in ('so_sped', 'complemento', 'estorno'):
                    deb_pis   = cta_pis_deb  if status_pis != 'estorno' else cta_pis_cred
                    ddesc_pis = desc_pis_deb if status_pis != 'estorno' else desc_pis_cred
                    cred_pis  = cta_pis_cred if status_pis != 'estorno' else cta_pis_deb
                    cdesc_pis = desc_pis_cred if status_pis != 'estorno' else desc_pis_deb
                    lancamentos.append(gerar_lancamento(
                        bloco="F100", codigo_conta=deb_pis, descricao_conta=ddesc_pis,
                        debito=delta_pis, credito='',
                        descricao=descricao, centro_de_custo=cc_pis, filial=filial
                    ))
                    lancamentos.append(gerar_lancamento(
                        bloco="F100", codigo_conta=cred_pis, descricao_conta=cdesc_pis,
                        debito='', credito=delta_pis,
                        descricao=descricao, centro_de_custo=cc_pis, filial=filial
                    ))

            # --- COFINS ---
            if _parse_valor(vl_cofins_sped):
                match_cofins = sap_cofins[sap_cofins['Valor'].apply(_parse_valor) == _parse_valor(vl_cofins_sped)]
                if not match_cofins.empty:
                    vl_sap_cofins               = match_cofins.iloc[0]['Valor']
                    delta_cofins, status_cofins = comparacao_valores(vl_sap_cofins, vl_cofins_sped)
                    cc_cofins                   = match_cofins.iloc[0].get('Centro de Custo', '')
                else:
                    vl_sap_cofins = ''
                    delta_cofins  = _parse_valor(vl_cofins_sped) or 0
                    status_cofins = 'so_sped'
                    cc_cofins     = ''

                registros.append(gerar_registro(
                    bloco="F100", num_doc=desc, identificador=desc,
                    imposto="COFINS", vl_sped=vl_cofins_sped, vl_sap=vl_sap_cofins, status=status_cofins
                ))

                if status_cofins in ('so_sped', 'complemento', 'estorno'):
                    deb_cof   = cta_cof_deb  if status_cofins != 'estorno' else cta_cof_cred
                    ddesc_cof = desc_cof_deb if status_cofins != 'estorno' else desc_cof_cred
                    cred_cof  = cta_cof_cred if status_cofins != 'estorno' else cta_cof_deb
                    cdesc_cof = desc_cof_cred if status_cofins != 'estorno' else desc_cof_deb
                    lancamentos.append(gerar_lancamento(
                        bloco="F100", codigo_conta=deb_cof, descricao_conta=ddesc_cof,
                        debito=delta_cofins, credito='',
                        descricao=descricao, centro_de_custo=cc_cofins, filial=filial
                    ))
                    lancamentos.append(gerar_lancamento(
                        bloco="F100", codigo_conta=cred_cof, descricao_conta=cdesc_cof,
                        debito='', credito=delta_cofins,
                        descricao=descricao, centro_de_custo=cc_cofins, filial=filial
                    ))

    def _validar_f120():
        if df_bloco_f120.empty:
            return

        sap_pis    = df_sap[df_sap['Imposto'] == 'PIS']
        sap_cofins = df_sap[df_sap['Imposto'] == 'COFINS']

        for _, registro in df_bloco_f120.iterrows():
            desc           = registro.get('DESC_BEM_IMOB', '')
            ind_oper       = registro.get('IND_OPER', '0')
            vl_pis_sped    = registro.get('VL_PIS', '')
            vl_cofins_sped = registro.get('VL_COFINS', '')
            filial         = registro.get('CNPJ_ESTAB', '')
            descricao      = f"F120 - {desc}"

            if ind_oper == '0':
                cta_pis_deb,  desc_pis_deb  = '1.01.05.01.0003', 'PIS a Recuperar'
                cta_pis_cred, desc_pis_cred = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_cof_deb,  desc_cof_deb  = '1.01.05.01.0004', 'COFINS a Recuperar'
                cta_cof_cred, desc_cof_cred = '3.01.01.03.0004', '( - ) COFINS'
            else:
                cta_pis_deb,  desc_pis_deb  = '3.01.01.03.0003', '( - ) PIS/PASEP'
                cta_pis_cred, desc_pis_cred = '2.01.01.04.0002', 'PIS a Recolher'
                cta_cof_deb,  desc_cof_deb  = '3.01.01.03.0004', '( - ) COFINS'
                cta_cof_cred, desc_cof_cred = '2.01.01.04.0003', 'COFINS a Recolher'

            # --- PIS ---
            if _parse_valor(vl_pis_sped):
                match_pis = sap_pis[sap_pis['Valor'].apply(_parse_valor) == _parse_valor(vl_pis_sped)]
                if not match_pis.empty:
                    vl_sap_pis            = match_pis.iloc[0]['Valor']
                    delta_pis, status_pis = comparacao_valores(vl_sap_pis, vl_pis_sped)
                    cc_pis                = match_pis.iloc[0].get('Centro de Custo', '')
                else:
                    vl_sap_pis = ''
                    delta_pis  = _parse_valor(vl_pis_sped) or 0
                    status_pis = 'so_sped'
                    cc_pis     = ''

                registros.append(gerar_registro(
                    bloco="F120", num_doc=desc, identificador=desc,
                    imposto="PIS", vl_sped=vl_pis_sped, vl_sap=vl_sap_pis, status=status_pis
                ))

                if status_pis in ('so_sped', 'complemento', 'estorno'):
                    deb_pis   = cta_pis_deb  if status_pis != 'estorno' else cta_pis_cred
                    ddesc_pis = desc_pis_deb if status_pis != 'estorno' else desc_pis_cred
                    cred_pis  = cta_pis_cred if status_pis != 'estorno' else cta_pis_deb
                    cdesc_pis = desc_pis_cred if status_pis != 'estorno' else desc_pis_deb
                    lancamentos.append(gerar_lancamento(
                        bloco="F120", codigo_conta=deb_pis, descricao_conta=ddesc_pis,
                        debito=delta_pis, credito='',
                        descricao=descricao, centro_de_custo=cc_pis, filial=filial
                    ))
                    lancamentos.append(gerar_lancamento(
                        bloco="F120", codigo_conta=cred_pis, descricao_conta=cdesc_pis,
                        debito='', credito=delta_pis,
                        descricao=descricao, centro_de_custo=cc_pis, filial=filial
                    ))

            # --- COFINS ---
            if _parse_valor(vl_cofins_sped):
                match_cofins = sap_cofins[sap_cofins['Valor'].apply(_parse_valor) == _parse_valor(vl_cofins_sped)]
                if not match_cofins.empty:
                    vl_sap_cofins               = match_cofins.iloc[0]['Valor']
                    delta_cofins, status_cofins = comparacao_valores(vl_sap_cofins, vl_cofins_sped)
                    cc_cofins                   = match_cofins.iloc[0].get('Centro de Custo', '')
                else:
                    vl_sap_cofins = ''
                    delta_cofins  = _parse_valor(vl_cofins_sped) or 0
                    status_cofins = 'so_sped'
                    cc_cofins     = ''

                registros.append(gerar_registro(
                    bloco="F120", num_doc=desc, identificador=desc,
                    imposto="COFINS", vl_sped=vl_cofins_sped, vl_sap=vl_sap_cofins, status=status_cofins
                ))

                if status_cofins in ('so_sped', 'complemento', 'estorno'):
                    deb_cof   = cta_cof_deb  if status_cofins != 'estorno' else cta_cof_cred
                    ddesc_cof = desc_cof_deb if status_cofins != 'estorno' else desc_cof_cred
                    cred_cof  = cta_cof_cred if status_cofins != 'estorno' else cta_cof_deb
                    cdesc_cof = desc_cof_cred if status_cofins != 'estorno' else desc_cof_deb
                    lancamentos.append(gerar_lancamento(
                        bloco="F120", codigo_conta=deb_cof, descricao_conta=ddesc_cof,
                        debito=delta_cofins, credito='',
                        descricao=descricao, centro_de_custo=cc_cofins, filial=filial
                    ))
                    lancamentos.append(gerar_lancamento(
                        bloco="F120", codigo_conta=cred_cof, descricao_conta=cdesc_cof,
                        debito='', credito=delta_cofins,
                        descricao=descricao, centro_de_custo=cc_cofins, filial=filial
                    ))

    def _validar_m110():
        if df_bloco_M110.empty:
            return

        cnpj = df_bloco_0000.iloc[0]['CNPJ']

        for _, registro in df_bloco_M110.iterrows():
            num_doc = registro.get('NUM_DOC', '')
            vl_aj   = registro.get('VL_AJ', '')
            ind_aj  = registro.get('IND_AJ', '')

            registros.append(gerar_registro(
                bloco="M110", num_doc=num_doc, identificador=num_doc,
                imposto="PIS", vl_sped=vl_aj, vl_sap="", status="so_sped"
            ))

            lancamentos.append(gerar_lancamento(
                bloco="M110",
                codigo_conta="4.01.01.01.0001" if ind_aj == '0' else "1.01.05.01.0003",
                descricao_conta="Custo dos Produtos Vendidos" if ind_aj == '0' else "PIS a Recuperar",
                debito=vl_aj, credito="",
                descricao="M110", centro_de_custo="OBRAS", filial=cnpj
            ))
            lancamentos.append(gerar_lancamento(
                bloco="M110",
                codigo_conta="1.01.05.01.0003" if ind_aj == '0' else "4.01.01.01.0001",
                descricao_conta="PIS a Recuperar" if ind_aj == '0' else "Custo dos Produtos Vendidos",
                debito="", credito=vl_aj,
                descricao="M110", centro_de_custo="OBRAS", filial=cnpj
            ))

    def _validar_m215():
        if df_bloco_M215.empty:
            return

        cnpj = df_bloco_0000.iloc[0]['CNPJ']

        for _, registro in df_bloco_M215.iterrows():
            num_doc  = registro.get('NUM_DOC', '')
            vl_aj_bc = registro.get('VL_AJ_BC', '')
            ind_aj   = registro.get('IND_AJ_BC', '')
            vl_calc  = (_parse_valor(vl_aj_bc) or 0) * 0.0165

            registros.append(gerar_registro(
                bloco="M215", num_doc=num_doc, identificador=num_doc,
                imposto="PIS", vl_sped=vl_aj_bc, vl_sap="", status="so_sped"
            ))

            lancamentos.append(gerar_lancamento(
                bloco="M215",
                codigo_conta="2.01.01.04.0002" if ind_aj == '0' else "1.01.05.01.0003",
                descricao_conta="PIS a Recolher" if ind_aj == '0' else "PIS a Recuperar",
                debito=vl_calc, credito="",
                descricao="M215", centro_de_custo="OBRAS", filial=cnpj
            ))
            lancamentos.append(gerar_lancamento(
                bloco="M215",
                codigo_conta="1.01.05.01.0003" if ind_aj == '0' else "2.01.01.04.0002",
                descricao_conta="PIS a Recuperar" if ind_aj == '0' else "PIS a Recolher",
                debito="", credito=vl_calc,
                descricao="M215", centro_de_custo="OBRAS", filial=cnpj
            ))

    def _validar_m510():
        if df_bloco_M510.empty:
            return

        cnpj = df_bloco_0000.iloc[0]['CNPJ']

        for _, registro in df_bloco_M510.iterrows():
            num_doc = registro.get('NUM_DOC', '')
            vl_aj   = registro.get('VL_AJ', '')
            ind_aj  = registro.get('IND_AJ', '')

            registros.append(gerar_registro(
                bloco="M510", num_doc=num_doc, identificador=num_doc,
                imposto="COFINS", vl_sped=vl_aj, vl_sap="", status="so_sped"
            ))

            lancamentos.append(gerar_lancamento(
                bloco="M510",
                codigo_conta="4.01.01.01.0001" if ind_aj == '0' else "1.01.05.01.0004",
                descricao_conta="Custo dos Produtos Vendidos" if ind_aj == '0' else "COFINS a Recuperar",
                debito=vl_aj, credito="",
                descricao="M510", centro_de_custo="OBRAS", filial=cnpj
            ))
            lancamentos.append(gerar_lancamento(
                bloco="M510",
                codigo_conta="1.01.05.01.0004" if ind_aj == '0' else "4.01.01.01.0001",
                descricao_conta="COFINS a Recuperar" if ind_aj == '0' else "Custo dos Produtos Vendidos",
                debito="", credito=vl_aj,
                descricao="M510", centro_de_custo="OBRAS", filial=cnpj
            ))

    def _validar_m615():
        if df_bloco_M615.empty:
            return

        cnpj = df_bloco_0000.iloc[0]['CNPJ']

        for _, registro in df_bloco_M615.iterrows():
            num_doc  = registro.get('NUM_DOC', '')
            vl_aj_bc = registro.get('VL_AJ_BC', '')
            ind_aj   = registro.get('IND_AJ_BC', '')
            vl_calc  = (_parse_valor(vl_aj_bc) or 0) * 0.076

            registros.append(gerar_registro(
                bloco="M615", num_doc=num_doc, identificador=num_doc,
                imposto="COFINS", vl_sped=vl_aj_bc, vl_sap="", status="so_sped"
            ))

            lancamentos.append(gerar_lancamento(
                bloco="M615",
                codigo_conta="2.01.01.04.0003" if ind_aj == '0' else "1.01.05.01.0004",
                descricao_conta="COFINS a Recolher" if ind_aj == '0' else "COFINS a Recuperar",
                debito=vl_calc, credito="",
                descricao="M615", centro_de_custo="OBRAS", filial=cnpj
            ))
            lancamentos.append(gerar_lancamento(
                bloco="M615",
                codigo_conta="1.01.05.01.0004" if ind_aj == '0' else "2.01.01.04.0003",
                descricao_conta="COFINS a Recuperar" if ind_aj == '0' else "COFINS a Recolher",
                debito="", credito=vl_calc,
                descricao="M615", centro_de_custo="OBRAS", filial=cnpj
            ))

    # Executa todas as validações SPED → SAP
    _validar_a100()
    _validar_c100()
    _validar_c501()
    _validar_c505()
    _validar_d101()
    _validar_d105()
    _validar_f100()
    _validar_f120()
    _validar_m110()
    _validar_m215()
    _validar_m510()
    _validar_m615()

    # Coleta chaves NUM_DOC presentes no SPED (blocos pareados por Ref.3)
    _nums_sped = set()
    for _df in [df_bloco_c100, df_bloco_c501, df_bloco_c505, df_bloco_d101, df_bloco_d105]:
        if not _df.empty and 'NUM_DOC' in _df.columns:
            _nums_sped.update(_df['NUM_DOC'].dropna().tolist())

    # Coleta valores PIS/COFINS presentes no SPED (blocos pareados por valor)
    _vals_pis_sped    = set()
    _vals_cofins_sped = set()
    for _df in [df_bloco_a100, df_bloco_f100, df_bloco_f120]:
        if not _df.empty:
            if 'VL_PIS' in _df.columns:
                _vals_pis_sped.update(_df['VL_PIS'].apply(_parse_valor).dropna().tolist())
            if 'VL_COFINS' in _df.columns:
                _vals_cofins_sped.update(_df['VL_COFINS'].apply(_parse_valor).dropna().tolist())

    # Registros SAP sem correspondência no SPED → so_sap
    for _, registro in df_sap.iterrows():
        ref     = registro.get('Ref.3 (Linha)', '')
        imposto = registro.get('Imposto', '')
        valor   = _parse_valor(registro.get('Valor', ''))

        matched = (
            ref in _nums_sped
            or (imposto == 'PIS'    and valor in _vals_pis_sped)
            or (imposto == 'COFINS' and valor in _vals_cofins_sped)
        )

        if not matched:
            num_doc_sap = registro.get('Nº doc.', '')
            valor_sap   = registro.get('Valor', '')

            registros.append(gerar_registro(
                bloco='SAP',
                num_doc=num_doc_sap,
                identificador=ref,
                imposto=imposto,
                vl_sped='',
                vl_sap=valor_sap,
                status='so_sap'
            ))

            cta_deb   = registro.get('Cta.contáb./cód.PN(D)', '')
            desc_deb  = registro.get('Cta.cont./Nome PN(D)', '')
            cta_cred  = registro.get('Cta.contáb./cód.PN(C)', '')
            desc_cred = registro.get('Cta.cont./Nome PN(C)', '')
            descricao_lanc = f"Estorno SAP - {num_doc_sap}"

            lancamentos.append(gerar_lancamento(
                bloco='SAP',
                codigo_conta=cta_cred,
                descricao_conta=desc_cred,
                debito=valor_sap,
                credito='',
                descricao=descricao_lanc,
                centro_de_custo='',
                filial=''
            ))
            lancamentos.append(gerar_lancamento(
                bloco='SAP',
                codigo_conta=cta_deb,
                descricao_conta=desc_deb,
                debito='',
                credito=valor_sap,
                descricao=descricao_lanc,
                centro_de_custo='',
                filial=''
            ))

    return {
        'lancamentos': [{k: _clean(v) for k, v in l.items()} for l in lancamentos],
        'registros':   [{k: _clean(v) for k, v in r.items()} for r in registros],
    }
