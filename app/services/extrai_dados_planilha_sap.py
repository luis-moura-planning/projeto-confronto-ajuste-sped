import openpyxl
from datetime import datetime


def extrair_por_nota(caminho_arquivo: str) -> dict:
    """
    Lê o arquivo xlsx e retorna um dicionário onde cada chave é o número
    do documento (Nº doc.) e o valor contém os dados da nota e seus lançamentos.

    Parâmetros:
        caminho_arquivo: Caminho para o arquivo .xlsx

    Retorno:
        {
            "NS 5882": {
                "seq": 1,
                "num_transacao": 62170,
                "data_lancamento": "2026-02-21",   # ou int se não for data válida
                "serie": "Primário",
                "num_doc": "NS 5882",
                "observacoes": "Notas Fiscais de Saída - C01241",
                "lancamentos": [
                    {
                        "cta_contabil": "C01241",
                        "nome_pn": "GOIAS ALIMENTOS S.A",
                        "debito_credito": 347.0,
                        "observacoes": "...",
                        "contrato_guarda_chuva": "",
                        "num_seq_salvo": "",
                        "centro_custo": "",
                        "frota": ""
                    },
                    ...
                ]
            },
            ...
        }
    """
    wb = openpyxl.load_workbook(caminho_arquivo, read_only=True, data_only=True)
    ws = wb.active

    # Lê todas as linhas (pula o cabeçalho)
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    notas = {}
    nota_atual = None

    for row in rows:
        (seq, num_transacao, data_lanc, serie, num_doc,
         cta_contabil, nome_pn, debito_credito, observacoes,
         contrato, num_seq_salvo, centro_custo, frota) = row[:13]

        # Linha de cabeçalho da nota: tem Nº seq. preenchido
        if seq is not None:
            # Formata a data se for um objeto datetime ou número serial
            if isinstance(data_lanc, datetime):
                data_str = data_lanc.strftime("%Y-%m-%d")
            else:
                data_str = data_lanc  # mantém como está (int ou str)

            nota_atual = str(num_doc).strip() if num_doc else f"seq_{seq}"
            notas[nota_atual] = {
                "seq": seq,
                "num_transacao": num_transacao,
                "data_lancamento": data_str,
                "serie": serie,
                "num_doc": num_doc,
                "observacoes": observacoes,
                "lancamentos": []
            }

        # Linha de lançamento: seq vazio, mas pertence à nota atual
        elif nota_atual is not None and cta_contabil is not None:
            lancamento = {
                "cta_contabil": cta_contabil,
                "nome_pn": nome_pn,
                "debito_credito": debito_credito,
                "observacoes": observacoes,
                "contrato_guarda_chuva": contrato,
                "num_seq_salvo": num_seq_salvo,
                "centro_custo": centro_custo,
                "frota": frota
            }
            notas[nota_atual]["lancamentos"].append(lancamento)

    wb.close()
    return notas


# ── Exemplo de uso ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    arquivo = "analise_arquivo.xlsx"   # ajuste o caminho se necessário
    dados = extrair_por_nota(arquivo)

    # Exibe as 2 primeiras notas como exemplo
    primeiras = dict(list(dados.items())[:2])
    print(json.dumps(primeiras, ensure_ascii=False, indent=2, default=str))

    print(f"\nTotal de notas extraídas: {len(dados)}")