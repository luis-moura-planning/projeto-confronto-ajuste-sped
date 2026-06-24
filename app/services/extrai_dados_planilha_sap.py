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
            'PIS a Recuperar',
            'COFINS a Recuperar',
            'PIS a Recolher',
            'COFINS a Recolher',
            '( - ) PIS/PASEP',
            '( - ) COFINS',
            '(-) PIS s/ Receitas Financeiras',
            '(-) COFINS s/ Receitas Financeiras',
            '(-) Pis s/ Alugués',
            '(-) Cofins s/ Aluguéis',
            '(-) Pis s/ Energia',
            '(-) Cofins s/ Energia',
            '(-) Pis s/ Depreciação',
            '(-) Cofins s/ Depreciação',
        ]

        df_pis_cofins = df[
            df['Cta.cont./Nome PN'].isin(contas_filtradas)
        ].copy()

        df_pis_cofins_debito = df_pis_cofins.loc[df_pis_cofins['Débito (MC)'].notna()]
        df_pis_cofins_debito = df_pis_cofins_debito.rename(columns={
            'Data de lançamento' :  'Data de lançamento(D)',
            'Nº doc.' : 'Nº doc.(D)',
            'Ref.3 (Linha)' : 'Ref.3 (Linha)(D)',
            'Cta.contáb./cód.PN' : 'Cta.contáb./cód.PN(D)',
            'Cta.cont./Nome PN' : 'Cta.cont./Nome PN(D)',
            'Débito (MC)' : 'Débito (MC)(D)',
            'Crédito (MC)': 'Crédito (MC)(D)',
            'Observações' : 'Observações(D)'
        })

        df_pis_cofins_credito = df_pis_cofins.loc[df_pis_cofins['Crédito (MC)'].notna()]
        df_pis_cofins_credito = df_pis_cofins_credito.rename(columns={
            'Data de lançamento' :  'Data de lançamento(C)',
            'Nº doc.' : 'Nº doc.(C)',
            'Ref.3 (Linha)' : 'Ref.3 (Linha)(C)',
            'Cta.contáb./cód.PN' : 'Cta.contáb./cód.PN(C)',
            'Cta.cont./Nome PN' : 'Cta.cont./Nome PN(C)',
            'Débito (MC)' : 'Débito (MC)(C)',
            'Crédito (MC)': 'Crédito (MC)(C)',
            'Observações' : 'Observações(C)'
        })

        df_pis_cofins = pd.merge(
            df_pis_cofins_debito, df_pis_cofins_credito, 
            left_on=['Data de lançamento(D)','Ref.3 (Linha)(D)', 'Débito (MC)(D)', 'Observações(D)'], 
            right_on=['Data de lançamento(C)','Ref.3 (Linha)(C)', 'Crédito (MC)(C)','Observações(C)'], 
            how='outer')
        
        df_pis_cofins['Data de lançamento(D)'] = (
        df_pis_cofins['Data de lançamento(D)']
        .combine_first(df_pis_cofins['Data de lançamento(C)'])
        )

        df_pis_cofins['Nº doc.(D)'] = (
        df_pis_cofins['Nº doc.(D)']
        .combine_first(df_pis_cofins['Nº doc.(C)'])
        )

        df_pis_cofins['Ref.3 (Linha)(D)'] = (
        df_pis_cofins['Ref.3 (Linha)(D)']
        .combine_first(df_pis_cofins['Ref.3 (Linha)(C)'])
        )

        df_pis_cofins['Observações(D)'] = (
        df_pis_cofins['Observações(D)']
        .combine_first(df_pis_cofins['Observações(C)'])
        )
        
        df_pis_cofins = df_pis_cofins[[
            'Data de lançamento(D)', 
            'Nº doc.(D)', 
            'Ref.3 (Linha)(D)', 
            'Cta.contáb./cód.PN(D)', 
            'Cta.cont./Nome PN(D)',
            'Débito (MC)(D)',
            'Cta.contáb./cód.PN(C)', 
            'Cta.cont./Nome PN(C)',
            'Crédito (MC)(C)',
            'Observações(D)'
        ]]

        df_pis_cofins['Valor'] = (
            df_pis_cofins['Débito (MC)(D)'].combine_first(df_pis_cofins['Crédito (MC)(C)'])
        )

        df_pis_cofins['Imposto'] = pd.NA

        df_pis_cofins.loc[
            df_pis_cofins['Cta.cont./Nome PN(D)'].str.contains('PIS', case=False, na=False) |
            df_pis_cofins['Cta.cont./Nome PN(C)'].str.contains('PIS', case=False, na=False),
            'Imposto'
        ] = 'PIS'

        df_pis_cofins.loc[
            df_pis_cofins['Cta.cont./Nome PN(D)'].str.contains('COFINS', case=False, na=False) |
            df_pis_cofins['Cta.cont./Nome PN(C)'].str.contains('COFINS', case=False, na=False),
            'Imposto'
        ] = 'COFINS'

        df_pis_cofins = df_pis_cofins.rename(columns={
            'Data de lançamento(D)': 'Data de lançamento',
            'Nº doc.(D)' : 'Nº doc.',
            'Ref.3 (Linha)(D)' : 'Ref.3 (Linha)',
            'Observações(D)' : 'Observações'
        })

        return df_pis_cofins

    except Exception as e:
        raise RuntimeError(f"Erro ao processar planilha SAP: {e}")
    
# dados_sap = extrai_dados_planilha_sap(r'C:\Users\luis.moura\Documents\GitHub\projeto-confronto-ajuste-sped\diarios_test\Diário 03.2026 - Central.xlsx')
# #print(dados_sap.info())
# dados_sap.to_excel("dados_sap_novo.xlsx", index=False)
    