import pandas as pd


def extrai_dados_planilha_sap(planilha_xlsx):
    sheet_name = "Sheet1"

    try:
        arquivo = pd.ExcelFile(planilha_xlsx)

        if sheet_name not in arquivo.sheet_names:
            raise ValueError(
                f"Aba '{sheet_name}' não encontrada. Disponíveis: {arquivo.sheet_names}"
            )

        df = pd.read_excel(arquivo, sheet_name=sheet_name)

        colunas = [
            'Data de lançamento', 'Nº doc.', 'Ref.3 (Linha)', 'Cta.contáb./cód.PN',
            'Cta.cont./Nome PN', 'Débito (MC)', 'Crédito (MC)', 'Observações', 'Centro de Custo'
        ]

        # valida colunas
        missing = set(colunas) - set(df.columns)
        if missing:
            raise ValueError(f"Colunas ausentes na planilha: {missing}")

        df = df.loc[:, colunas]

        df['Nº doc.'] = df['Nº doc.'].astype("string")

        df['Nº doc.'] = df['Nº doc.'].replace(r"^\s*$", pd.NA, regex=True)

        prefixo = df['Nº doc.'].str.extract(r"^\s*([A-Za-z]+)", expand=False)

        df['Nº doc.'] = df['Nº doc.'].where(prefixo.isna(), prefixo)
        df['Nº doc.'] = df['Nº doc.'].ffill()

        contas_filtradas = [
            'PIS a Recolher', '( - ) PIS/PASEP', '(-) Pis s/ Depreciação',
            '(-) PIS s/ Receitas Financeiras', 'COFINS a Recolher',
            '( - ) COFINS', '(-) Cofins s/ Depreciação',
            '(-) COFINS s/ Receitas Financeiras'
        ]

        df_pis_cofins = df[
            df['Cta.cont./Nome PN'].isin(contas_filtradas)
        ].copy()

        df_pis_cofins_debito = df_pis_cofins.loc[df_pis_cofins['Débito (MC)'] != ""]
        df_pis_cofins_credito = df_pis_cofins.loc[df_pis_cofins['Crédito (MC)'] != ""]

        
        

        return df_pis_cofins

    except Exception as e:
        raise RuntimeError(f"Erro ao processar planilha SAP: {e}")
    