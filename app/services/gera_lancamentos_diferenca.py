"""
Gera lançamentos contábeis de ajuste com base nas diferenças
calculadas por compara_valores_diario_sped.comparar_por_nota().

Sinal da diferença (sap - sped):
  > 0 → SAP tem mais imposto que o SPED → débito ajuste / crédito "a Recolher"
  < 0 → SAP tem menos imposto que o SPED → débito "a Recolher" / crédito ajuste
"""

# Contas padrão por campo de imposto — usadas quando não extraídas do diário
# Fonte: sped_comparador.py (Central Irrigação)
CONTAS_TRIBUTOS = {
    'vl_pis': {
        'conta_debito':  '3.01.01.03.0003',
        'desc_debito':   '( - ) PIS/PASEP',
        'conta_credito': '2.01.01.04.0002',
        'desc_credito':  'PIS a Recolher',
    },
    'vl_cofins': {
        'conta_debito':  '3.01.01.03.0004',
        'desc_debito':   '( - ) COFINS',
        'conta_credito': '2.01.01.04.0003',
        'desc_credito':  'COFINS a Recolher',
    },
    'vl_icms': {
        'conta_debito':  '2.01.01.04.0001',
        'desc_debito':   'ICMS a Recolher',
        'conta_credito': '2.01.01.04.0001',
        'desc_credito':  'ICMS a Recolher',
    },
    'vl_cbs': {
        'conta_debito':  '3.01.01.03.0009',
        'desc_debito':   '(-) CBS',
        'conta_credito': '3.01.01.03.0009',
        'desc_credito':  '(-) CBS',
    },
    'vl_ibs': {
        'conta_debito':  '3.01.01.03.0010',
        'desc_debito':   '(-) IBS UF',
        'conta_credito': '3.01.01.03.0010',
        'desc_credito':  '(-) IBS UF',
    },
}

_CAMPOS_IMPOSTO = ('vl_pis', 'vl_cofins', 'vl_icms', 'vl_cbs', 'vl_ibs')


def gerar_lancamentos_diferenca(
    resultado_comparacao: dict,
    filial: str = '',
    centro_custo: str = '',
) -> list[dict]:
    """
    Gera lançamentos de ajuste para as diferenças encontradas entre SAP e SPED.

    Parâmetros:
        resultado_comparacao : retorno de comparar_por_nota()
        filial               : filial/empresa (preenchida se não vier do diário)
        centro_custo         : centro de custo fallback

    Retorno:
        Lista de dicts no formato:
        [
            {
                'nota':            '38639',
                'codigo_conta':    '2.01.01.04.0002',
                'descricao_conta': 'PIS a Recolher',
                'debito':          700.33,
                'credito':         None,
                'descricao':       'PIS a Recolher',
                'centro_custo':    'OBRAS',
                'filial':          'CENTRAL IRRIGACAO LTDA - Goiania',
            }, ...
        ]
    """
    lancamentos = []

    for chave, item in resultado_comparacao.items():
        if item['status'] != 'encontrado':
            continue

        diferenca = item['diferenca']
        chave_sap = item.get('chave_sap', chave)
        cc        = item.get('centro_custo') or centro_custo
        contas_nota = item.get('contas', {})

        for campo in _CAMPOS_IMPOSTO:
            diff = diferenca.get(campo, 0.0) or 0.0
            if diff == 0.0:
                continue

            # Usa contas extraídas do diário; cai em CONTAS_TRIBUTOS se incompleto
            config = dict(contas_nota.get(campo) or {})
            fallback = CONTAS_TRIBUTOS.get(campo, {})
            for lado in ('conta_debito', 'desc_debito', 'conta_credito', 'desc_credito'):
                if lado not in config:
                    config[lado] = fallback.get(lado, '')

            if not config.get('conta_debito') or not config.get('conta_credito'):
                continue

            valor = round(abs(diff), 2)

            if diff > 0:
                lancamentos.append(_linha(chave_sap, config['conta_debito'],  config['desc_debito'],  valor, None,  config['desc_debito'],  cc, filial))
                lancamentos.append(_linha(chave_sap, config['conta_credito'], config['desc_credito'], None,  valor, config['desc_credito'], cc, filial))
            else:
                lancamentos.append(_linha(chave_sap, config['conta_credito'], config['desc_credito'], valor, None,  config['desc_credito'], cc, filial))
                lancamentos.append(_linha(chave_sap, config['conta_debito'],  config['desc_debito'],  None,  valor, config['desc_debito'],  cc, filial))

    return lancamentos


def _linha(nota, codigo, descricao_conta, debito, credito, descricao, centro_custo, filial) -> dict:
    return {
        'nota':            nota,
        'codigo_conta':    codigo,
        'descricao_conta': descricao_conta,
        'debito':          debito,
        'credito':         credito,
        'descricao':       descricao,
        'centro_custo':    centro_custo,
        'filial':          filial,
    }
