# Documentação — Confronto Fiscal SPED × Razão

## Objetivo do Projeto

Ler o arquivo SPED EFD-Contribuições (PIS/COFINS), confrontar os valores com o razão contábil e gerar um arquivo de resultado para exportação com as divergências encontradas.

---

## Estado Atual

### O que já está pronto

| Arquivo | Função |
|---|---|
| `app.py` | Parse do `.txt` SPED, enriquecimento com hierarquia, inserção no PostgreSQL |
| `sped_metadata.json` | 203 registros com headers e hierarquia (bloco, nível, parent) |

### O que ainda precisa ser feito

- [ ] Leitura do razão contábil (fonte a definir — planilha, banco, API)
- [ ] Lógica de confronto SPED × razão por conta/período
- [ ] Geração do arquivo de resultado (Excel / CSV / JSON)
- [ ] Rotas Flask para expor o confronto via API

> As etapas de extração de metadados do `Manual_Sped.docx` e geração do DDL SQL foram movidas para outro projeto.

---

## Formato do Arquivo SPED

- Arquivo texto (`|`-delimitado), uma linha por registro
- Primeiro campo de cada linha = código `REG` (identifica o tipo do registro)
- Exemplo de linha: `|C100|0|1|0|55|...|1000.00|...|`
- Os registros aparecem em ordem hierárquica — filhos sempre após o pai

### Blocos relevantes para confronto fiscal

| Bloco | Conteúdo principal |
|---|---|
| `0` | Identificação da empresa, cadastro de participantes |
| `C` | Documentos fiscais — NF-e, NF, CT-e (receitas/entradas) |
| `D` | Documentos de transporte |
| `F` | Demais operações |
| `M` | Apuração PIS/COFINS (base de cálculo, alíquotas, débitos, créditos) |

---

## sped_metadata.json — Estrutura

```json
{
  "C100": {
    "bloco":     "C",
    "nivel":     3,
    "parent":    "C010",
    "fk_parent": "fk_c010",
    "headers":   ["REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", ...]
  }
}
```

**Campos:**

| Campo | Descrição |
|---|---|
| `bloco` | Letra/número do bloco SPED |
| `nivel` | Profundidade na hierarquia (0 = raiz, 1 = abertura de bloco, …) |
| `parent` | Código REG do registro pai direto |
| `fk_parent` | Nome da coluna FK correspondente no banco |
| `headers` | Lista ordenada dos campos do registro, na mesma ordem do arquivo |

---

## app.py — Funções disponíveis

### `parse_sped_binary(data: bytes) -> list[list[str]]`

Decodifica o arquivo SPED e retorna cada linha como lista de campos.

- Tenta encodings em ordem: `utf-8` → `latin-1` → `cp1252`
- Remove pipes externos e linhas vazias
- Retorna campos brutos sem nomes

```python
with open("arquivo.txt", "rb") as f:
    records_raw = parse_sped_binary(f.read())

# records_raw[0] → ['0000', '006', '0', '', '', '01032026', '31032026', ...]
```

---

### `carregar_metadata() -> dict`

Lê `sped_metadata.json` do projeto e retorna o dict completo.

```python
metadata = carregar_metadata()
# metadata["C100"]["headers"] → ["REG", "IND_OPER", ...]
```

---

### `record_to_obj(fields, headers_map) -> dict`

Converte uma lista de campos em dict nomeado usando os headers do metadata.

- Se o REG for desconhecido retorna `{"REG": reg, "_raw": fields}`

```python
headers_map = {reg: meta["headers"] for reg, meta in metadata.items()}
obj = record_to_obj(['C100', '0', '1', ...], headers_map)
# {'REG': 'C100', 'IND_OPER': '0', 'IND_EMIT': '1', ...}
```

---

### `enrich_records(records_raw, metadata) -> list[dict]`

Converte todos os registros brutos em dicts nomeados e adiciona chaves de hierarquia com base no número de linha (sem banco de dados).

**Chaves adicionadas a cada registro:**

| Chave | Tipo | Descrição |
|---|---|---|
| `_id` | `int` | Índice 0-based do registro no arquivo |
| `_fk_0000` | `int` | `_id` do registro `0000` pai (presente em todos exceto o próprio `0000`) |
| `_fk_{parent}` | `int` | `_id` do último registro pai direto visto (ex: `_fk_c010` em `C100`) |

```python
records = enrich_records(records_raw, metadata)

# records[5] → {
#   'REG': 'C100', 'IND_OPER': '0', ...,
#   '_id': 5,
#   '_fk_0000': 0,
#   '_fk_c010': 3
# }
```

---

### `inserir_sped_no_banco(records_raw, metadata, conn) -> int`

Insere todos os registros no PostgreSQL mantendo as FKs de hierarquia.

- Rastreia o último `id` real (via `RETURNING id`) inserido por tipo de REG
- Preenche `fk_0000` e `fk_{parent}` automaticamente
- Normaliza nomes de colunas para corresponder ao DDL gerado
- Faz `commit` ao final; retorna total de linhas inseridas

```python
import psycopg2

conn = psycopg2.connect(
    host="localhost", dbname="meu_banco",
    user="postgres", password="senha"
)
metadata    = carregar_metadata()
records_raw = parse_sped_binary(open("arquivo.txt", "rb").read())

total = inserir_sped_no_banco(records_raw, metadata, conn)
conn.close()
```

---

### `gerenciar_notas()` (função de teste local)

Lê o arquivo SPED de `arquivos_base/`, roda `enrich_records` e salva o resultado em `sped_records.json`.

```python
# Executar direto:
python app.py
# → gera sped_records.json com todos os registros enriquecidos
```

---

## Normalização de nomes de colunas — `_col_db(name)`

Garante que os nomes de campos usados nos `INSERT` correspondam exatamente aos identificadores criados no DDL:

1. Remove acentos via `unicodedata.NFD` → `NIVEL`, `PERIODO`
2. Remove caracteres inválidos `[^A-Za-z0-9_]` → elimina espaços, `;`, etc.
3. Envolve em aspas duplas se for palavra reservada PostgreSQL → `"END"`

---

## Próximas Etapas

### 1. Leitura do razão contábil

Definir a fonte dos dados do razão:
- Planilha Excel (via `openpyxl` ou `pandas`)
- Banco de dados existente (query direta)
- Arquivo exportado do ERP

### 2. Lógica de confronto

Para cada período apurado no SPED (identificado pelo `0000`):
- Comparar valores de base de cálculo PIS/COFINS (bloco M) com o razão
- Identificar contas contábeis vinculadas (bloco 0500 / 0600)
- Calcular diferenças: `valor_sped - valor_razao`

### 3. Arquivo de resultado

Gerar saída com divergências encontradas:
- Colunas sugeridas: período, conta, descrição, valor SPED, valor razão, diferença, status
- Formatos: Excel (`.xlsx`) ou CSV

### 4. Rota Flask

```python
@app.route("/confronto", methods=["POST"])
def confronto():
    # recebe arquivo SPED + razão
    # retorna JSON com divergências ou arquivo para download
```

---

## Dependências

```
flask
psycopg2-binary
```

Instalar:
```bash
pip install flask psycopg2-binary
```
