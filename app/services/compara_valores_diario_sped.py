import re

# ── Padrões de impostos (busca em cta_contabil + nome_pn) ─────────────────────
_PADROES_IMPOSTO = {
    'icms':   re.compile(r'\bICMS\b',   re.IGNORECASE),
    'pis':    re.compile(r'\bPIS\b',    re.IGNORECASE),
    'cofins': re.compile(r'\bCOFINS\b', re.IGNORECASE),
    'cbs':    re.compile(r'\bCBS\b',    re.IGNORECASE),
    'ibs':    re.compile(r'\bIBS\b',    re.IGNORECASE),
}

# Conta de parceiro no SAP: "C" seguido de dígitos (ex: C01241, C01812)
_RE_CONTA_PARCEIRO = re.compile(r'^C\d+$')

_CAMPOS = ('vl_doc', 'vl_icms', 'vl_pis', 'vl_cofins', 'vl_cbs', 'vl_ibs')


def _normalizar_chave_sap(chave: str) -> str:
    """Remove prefixo alfabético do num_doc SAP: 'NS 5882' → '5882'."""
    return re.sub(r'^[A-Za-z\s]+', '', str(chave)).strip()


def _tipo_imposto(cta: str, nome: str) -> str | None:
    texto = f"{cta} {nome}"
    for tipo, padrao in _PADROES_IMPOSTO.items():
        if padrao.search(texto):
            return tipo
    return None


def _valores_sap(lancamentos: list) -> dict:
    """
    Extrai total e impostos dos lançamentos SAP.

    Regra de double-entry: cada imposto aparece exatamente duas vezes com o
    mesmo valor absoluto e sinais opostos (+x e -x). Para obter o valor real
    de cada imposto usamos sum(abs) / 2, que cancela a duplicidade.

    Total da nota: entrada na conta do parceiro (C0xxxx), que ocorre uma única
    vez. Basta tomar o valor absoluto.
    """
    totais_imposto: dict[str, float] = {t: 0.0 for t in _PADROES_IMPOSTO}
    vl_doc = 0.0

    for lanc in lancamentos:
        cta  = str(lanc.get('cta_contabil') or '').strip()
        nome = str(lanc.get('nome_pn')      or '').strip()
        val  = float(lanc.get('debito_credito') or 0)

        if _RE_CONTA_PARCEIRO.match(cta):
            # Conta do parceiro representa o total da nota (aparece 1x)
            vl_doc = abs(val)
            continue

        tipo = _tipo_imposto(cta, nome)
        if tipo:
            totais_imposto[tipo] += abs(val)

    return {
        'vl_doc':    round(vl_doc, 2),
        'vl_icms':   round(totais_imposto['icms']   / 2, 2),
        'vl_pis':    round(totais_imposto['pis']    / 2, 2),
        'vl_cofins': round(totais_imposto['cofins'] / 2, 2),
        'vl_cbs':    round(totais_imposto['cbs']    / 2, 2),
        'vl_ibs':    round(totais_imposto['ibs']    / 2, 2),
    }


def _valores_sped(nota: dict) -> dict:
    """Extrai os campos comparáveis de uma nota do SPED."""
    return {
        'vl_doc':    nota.get('vl_doc',    0.0),
        'vl_icms':   nota.get('vl_icms',   0.0),
        'vl_pis':    nota.get('vl_pis',    0.0),
        'vl_cofins': nota.get('vl_cofins', 0.0),
        'vl_cbs':    0.0,   # CBS/IBS ainda não extraído do SPED Contribuições
        'vl_ibs':    0.0,
    }


def comparar_por_nota(
    notas_sap:  dict,
    notas_sped: dict,
    mapeamento: dict | None = None,
) -> dict:
    """
    Compara valores por nota entre o diário SAP e o SPED.

    O num_doc SAP tem prefixo alfabético ("NS 5882") enquanto o SPED usa
    apenas o número ("5882"). Por padrão a função remove o prefixo
    automaticamente via ``_normalizar_chave_sap``.

    Um ``mapeamento`` {chave_sap → chave_sped} pode ser fornecido para casos
    onde a normalização automática não é suficiente.

    Parâmetros:
        notas_sap   : retorno de extrai_dados_planilha_sap.extrair_por_nota()
        notas_sped  : retorno de extrai_dados_sped.extrair_por_nota()
        mapeamento  : dict opcional {chave_sap → chave_sped}

    Retorno:
        {
            "chave_resultado": {
                "chave_sap":   "NS 5882",
                "chave_sped":  "38676",
                "status":      "encontrado" | "sem_sped" | "sem_sap",
                "sap": {
                    "vl_doc": 347.0, "vl_icms": 19.43,
                    "vl_pis": 0.0,   "vl_cofins": 0.0,
                    "vl_cbs": 2.95,  "vl_ibs": 0.33
                },
                "sped": {
                    "vl_doc": 347.0, "vl_icms": 19.43,
                    "vl_pis": 0.0,   "vl_cofins": 0.0,
                    "vl_cbs": 0.0,   "vl_ibs": 0.0
                },
                "diferenca": {          # sap - sped  (None se sem contraparte)
                    "vl_doc": 0.0, "vl_icms": 0.0,
                    "vl_pis": 0.0, "vl_cofins": 0.0,
                    "vl_cbs": 2.95, "vl_ibs": 0.33
                }
            },
            ...
        }
    """
    mapeamento = mapeamento or {}
    resultado: dict = {}

    # ── Notas do SAP ──────────────────────────────────────────────────────────
    sped_casadas: set = set()

    for chave_sap, nota_sap in notas_sap.items():
        # Mapeamento explícito tem prioridade; fallback: remove prefixo alfabético
        chave_sped = mapeamento.get(chave_sap, _normalizar_chave_sap(chave_sap))
        nota_sped  = notas_sped.get(chave_sped)

        sap_vals = _valores_sap(nota_sap['lancamentos'])

        if nota_sped is not None:
            sped_vals  = _valores_sped(nota_sped)
            diferenca  = {c: round(sap_vals[c] - sped_vals[c], 2) for c in _CAMPOS}
            status     = 'encontrado'
            sped_casadas.add(chave_sped)
        else:
            sped_vals = None
            diferenca = None
            status    = 'sem_sped'

        chave_result = chave_sped if nota_sped is not None else chave_sap
        resultado[chave_result] = {
            'chave_sap':  chave_sap,
            'chave_sped': chave_sped if nota_sped is not None else None,
            'status':     status,
            'sap':        sap_vals,
            'sped':       sped_vals,
            'diferenca':  diferenca,
        }

    # ── Notas do SPED sem contraparte no SAP ──────────────────────────────────
    for chave_sped, nota_sped in notas_sped.items():
        if chave_sped in sped_casadas:
            continue
        resultado[chave_sped] = {
            'chave_sap':  None,
            'chave_sped': chave_sped,
            'status':     'sem_sap',
            'sap':        None,
            'sped':       _valores_sped(nota_sped),
            'diferenca':  None,
        }

    return resultado


# ── Exemplo de uso ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import json
    from app.services.extrai_dados_planilha_sap import extrair_por_nota as sap_extrai
    from app.services.extrai_dados_sped          import extrair_por_nota as sped_extrai

    notas_sap  = sap_extrai('arquivos_auxiliares/arquivos_base/1 - Diario.xlsx')
    notas_sped = sped_extrai('arquivos_auxiliares/arquivos_base/2 - Sped Contribuicoes.txt')

    # Exemplo de mapeamento manual:  chave_sap → chave_sped
    # mapeamento = {'NS 5882': '38676', 'NS 5883': '38639'}
    mapeamento = {}

    resultado = comparar_por_nota(notas_sap, notas_sped, mapeamento)

    encontrados = {k: v for k, v in resultado.items() if v['status'] == 'encontrado'}
    sem_sped    = {k: v for k, v in resultado.items() if v['status'] == 'sem_sped'}
    sem_sap     = {k: v for k, v in resultado.items() if v['status'] == 'sem_sap'}

    print(f'Encontrados:  {len(encontrados)}')
    print(f'Sem SPED:     {len(sem_sped)}')
    print(f'Sem SAP:      {len(sem_sap)}')

    if encontrados:
        primeira = next(iter(encontrados.values()))
        print('\nExemplo de nota encontrada:')
        print(json.dumps(primeira, ensure_ascii=False, indent=2, default=str))
