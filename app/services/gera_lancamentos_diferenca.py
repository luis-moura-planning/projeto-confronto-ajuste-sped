"""
Gera lançamentos contábeis de ajuste com base nas diferenças
calculadas por compara_valores_diario_sped.comparar_por_nota().

Para cada diferença não-nula por tipo de imposto, produz um par
débito/crédito no formato:

    Código da Conta | Descrição da Conta | Débito | Crédito |
    Descrição | Centro de Custo | Filial

Sinal da diferença (sap - sped):
  > 0 → SAP tem mais imposto que o SPED:
        Débito  na conta de ajuste     (aumenta despesa/ativo)
        Crédito na conta "a Recolher"  (aumenta o passivo)
  < 0 → SAP tem menos imposto que o SPED:
        Débito  na conta "a Recolher"  (reduz o passivo)
        Crédito na conta de ajuste     (reduz despesa/ativo)
"""

# Campos de impostos reconhecidos
_CAMPOS_IMPOSTO = ('vl_pis', 'vl_cofins', 'vl_icms', 'vl_cbs', 'vl_ibs')


def gerar_lancamentos_diferenca(
    resultado_comparacao: dict,
    configuracao_contas: dict,
    centro_custo: str = '',
    filial: str = '',
) -> list[dict]:
    """
    Gera lançamentos de ajuste para as diferenças encontradas entre SAP e SPED.

    Parâmetros:
        resultado_comparacao:
            Retorno de compara_valores_diario_sped.comparar_por_nota().

        configuracao_contas:
            Mapeamento de campo → contas débito/crédito. Exemplo:
            {
                'vl_pis': {
                    'conta_credito': '2.01.01.04.0002',
                    'desc_credito':  'PIS a Recolher',
                    'conta_debito':  '2.01.01.04.0003',
                    'desc_debito':   'Pagamento Pis',
                },
                'vl_cofins': {
                    'conta_credito': '2.01.01.04.0004',
                    'desc_credito':  'COFINS a Recolher',
                    'conta_debito':  '2.01.01.04.0005',
                    'desc_debito':   'Pagamento COFINS',
                },
                # vl_icms, vl_cbs, vl_ibs ...
            }

        centro_custo : Centro de custo a preencher nos lançamentos.
        filial       : Filial/empresa a preencher nos lançamentos.

    Retorno:
        Lista de dicts, cada um representando uma linha do lançamento:
        [
            {
                'nota':           '5882',
                'codigo_conta':   '2.01.01.04.0002',
                'descricao_conta':'PIS a Recolher',
                'debito':         None,
                'credito':        700.33,
                'descricao':      'PIS a Recolher',
                'centro_custo':   'OBRAS',
                'filial':         'CENTRAL IRRIGACAO LTDA - Goiania',
            },
            {
                'nota':           '5882',
                'codigo_conta':   '2.01.01.04.0003',
                'descricao_conta':'Pagamento Pis',
                'debito':         700.33,
                'credito':        None,
                'descricao':      'Pagamento Pis',
                'centro_custo':   'OBRAS',
                'filial':         'CENTRAL IRRIGACAO LTDA - Goiania',
            },
            ...
        ]
    """
    lancamentos = []

    for chave, item in resultado_comparacao.items():
        if item['status'] != 'encontrado':
            continue

        diferenca = item['diferenca']
        chave_sap = item.get('chave_sap', chave)

        for campo in _CAMPOS_IMPOSTO:
            diff = diferenca.get(campo, 0.0) or 0.0
            if diff == 0.0:
                continue

            config = configuracao_contas.get(campo)
            if not config:
                continue  # campo sem conta configurada: ignora

            valor = round(abs(diff), 2)

            if diff > 0:
                # SAP > SPED: aumenta passivo → débito ajuste / crédito "a Recolher"
                linha_debito = _linha(
                    nota=chave_sap,
                    codigo=config['conta_debito'],
                    descricao_conta=config['desc_debito'],
                    debito=valor,
                    credito=None,
                    descricao=config['desc_debito'],
                    centro_custo=centro_custo,
                    filial=filial,
                )
                linha_credito = _linha(
                    nota=chave_sap,
                    codigo=config['conta_credito'],
                    descricao_conta=config['desc_credito'],
                    debito=None,
                    credito=valor,
                    descricao=config['desc_credito'],
                    centro_custo=centro_custo,
                    filial=filial,
                )
            else:
                # SAP < SPED: reduz passivo → débito "a Recolher" / crédito ajuste
                linha_debito = _linha(
                    nota=chave_sap,
                    codigo=config['conta_credito'],
                    descricao_conta=config['desc_credito'],
                    debito=valor,
                    credito=None,
                    descricao=config['desc_credito'],
                    centro_custo=centro_custo,
                    filial=filial,
                )
                linha_credito = _linha(
                    nota=chave_sap,
                    codigo=config['conta_debito'],
                    descricao_conta=config['desc_debito'],
                    debito=None,
                    credito=valor,
                    descricao=config['desc_debito'],
                    centro_custo=centro_custo,
                    filial=filial,
                )

            lancamentos.append(linha_debito)
            lancamentos.append(linha_credito)

    return lancamentos


def _linha(
    nota: str,
    codigo: str,
    descricao_conta: str,
    debito,
    credito,
    descricao: str,
    centro_custo: str,
    filial: str,
) -> dict:
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


# ── Exemplo de uso ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import json

    # Simulação de resultado do comparar_por_nota
    resultado_simulado = {
        'NS 5882': {
            'status':    'encontrado',
            'chave_sap': 'NS 5882',
            'diferenca': {
                'vl_doc':    0.0,
                'vl_icms':   0.0,
                'vl_pis':    700.33,
                'vl_cofins': 0.0,
                'vl_cbs':    0.0,
                'vl_ibs':    0.0,
            },
        }
    }

    CONTAS = {
        'vl_pis': {
            'conta_credito': '2.01.01.04.0002',
            'desc_credito':  'PIS a Recolher',
            'conta_debito':  '2.01.01.04.0003',
            'desc_debito':   'Pagamento Pis',
        },
        'vl_cofins': {
            'conta_credito': '2.01.01.04.0004',
            'desc_credito':  'COFINS a Recolher',
            'conta_debito':  '2.01.01.04.0005',
            'desc_debito':   'Pagamento COFINS',
        },
        'vl_icms': {
            'conta_credito': '2.01.01.04.0001',
            'desc_credito':  'ICMS a Recolher',
            'conta_debito':  '2.01.01.04.0006',
            'desc_debito':   'Pagamento ICMS',
        },
    }

    lancamentos = gerar_lancamentos_diferenca(
        resultado_comparacao=resultado_simulado,
        configuracao_contas=CONTAS,
        centro_custo='OBRAS',
        filial='CENTRAL IRRIGACAO LTDA - Goiania',
    )

    print(json.dumps(lancamentos, ensure_ascii=False, indent=2, default=str))
