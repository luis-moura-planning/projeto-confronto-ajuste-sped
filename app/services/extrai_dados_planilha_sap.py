import pandas as pd


def extrai_dados_planilha_sap(planilha_xlsx):
    sheet_name = "Sheet1"
    try:
        arquivo = pd.ExcelFile(planilha_xlsx)
        if sheet_name not in arquivo.sheet_names:
            raise ValueError(
                f"Aba '{sheet_name}' não encontrada. Disponíveis: {arquivo.sheet_names}"
            )
        return pd.read_excel(arquivo, sheet_name=sheet_name)
    except Exception as e:
        return str(e)
