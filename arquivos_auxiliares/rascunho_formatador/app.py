import json
import re
import unicodedata
from pathlib import Path

from flask import Flask

app = Flask(__name__)

# ── Normalização de nomes de colunas (espelha generate_sped_sql.py) ───────────
_PG_RESERVED = {
    "ALL","ANALYSE","ANALYZE","AND","ANY","ARRAY","AS","ASC","AUTHORIZATION",
    "BINARY","BOTH","CASE","CAST","CHECK","COLLATE","COLUMN","CONSTRAINT",
    "CREATE","CROSS","DEFAULT","DEFERRABLE","DESC","DISTINCT","DO","ELSE","END",
    "EXCEPT","FALSE","FETCH","FOR","FOREIGN","FROM","FULL","GRANT","GROUP",
    "HAVING","IN","INITIALLY","INNER","INTERSECT","INTO","IS","JOIN","LATERAL",
    "LEADING","LEFT","LIKE","LIMIT","NOT","NULL","OFFSET","ON","ONLY","OR",
    "ORDER","OUTER","PRIMARY","REFERENCES","RETURNING","RIGHT","SELECT",
    "SESSION_USER","SOME","SYMMETRIC","TABLE","THEN","TO","TRAILING","TRUE",
    "UNION","UNIQUE","USER","USING","WHEN","WHERE","WINDOW","WITH",
}

def _col_db(name: str) -> str:
    """Converte nome de campo SPED para o identificador SQL exato do banco."""
    name = unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9_]", "", name)
    return f'"{name}"' if name.upper() in _PG_RESERVED else name


# ── Parsing do arquivo SPED ───────────────────────────────────────────────────

def parse_sped_binary(data: bytes) -> list[list[str]]:
    """Recebe bytes de um arquivo SPED e retorna lista de registros (campos por '|')."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1", errors="replace")

    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(line.strip("|").split("|"))
    return records


# ── Metadata ──────────────────────────────────────────────────────────────────

def carregar_metadata() -> dict:
    path = Path(__file__).parent / "mapear_cabecario_sped/sped_metadata.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def record_to_obj(fields: list[str], headers_map: dict[str, list[str]]) -> dict:
    reg = fields[0] if fields else ""
    headers = headers_map.get(reg, [])
    return dict(zip(headers, fields)) if headers else {"REG": reg, "_raw": fields}


def enrich_records(records_raw: list[list[str]], metadata: dict) -> list[dict]:
    """
    Converte todos os registros brutos em dicts com campos nomeados e adiciona
    as chaves de hierarquia usando o número de linha como id:

      _id        → índice do registro na lista (0-based)
      _fk_0000   → _id do último registro 0000 visto (presente em todos exceto 0000)
      _fk_XXXX   → _id do último registro pai direto (ex: _fk_0140 em 0150)

    Útil para inspecionar a hierarquia antes de gravar no banco.
    """
    headers_map = {reg: meta["headers"] for reg, meta in metadata.items()}
    reg_last_line: dict[str, int] = {}
    result: list[dict] = []

    for idx, fields in enumerate(records_raw):
        reg  = fields[0] if fields else ""
        meta = metadata.get(reg, {})
        obj  = record_to_obj(fields, headers_map)

        obj["_id"] = idx

        nivel  = meta.get("nivel", -1)
        parent = meta.get("parent")

        if nivel != 0 and "0000" in reg_last_line:
            obj["_fk_0000"] = reg_last_line["0000"]

        if parent and parent in reg_last_line:
            obj[f"_fk_{parent.lower()}"] = reg_last_line[parent]

        reg_last_line[reg] = idx
        result.append(obj)

    return result


# ── Inserção no PostgreSQL ────────────────────────────────────────────────────

def inserir_sped_no_banco(
    records_raw: list[list[str]],
    metadata: dict,
    conn,
) -> int:
    """
    Insere todos os registros SPED no banco via conn (psycopg2 connection).

    A hierarquia é mantida automaticamente:
      - fk_0000  → id do último registro 0000 inserido (raiz da escrituração)
      - fk_XXXX  → id do último registro pai direto conforme sped_metadata.json

    Retorna o total de linhas inseridas.

    Exemplo de uso:
        import psycopg2
        conn = psycopg2.connect("host=localhost dbname=mydb user=postgres password=...")
        meta = carregar_metadata()
        with open("arquivo.txt", "rb") as f:
            records = parse_sped_binary(f.read())
        total = inserir_sped_no_banco(records, meta, conn)
        conn.close()
    """
    headers_map = {reg: meta["headers"] for reg, meta in metadata.items()}

    # Rastreia o último id inserido por tipo de REG
    reg_last_id: dict[str, int] = {}
    total = 0

    with conn.cursor() as cur:
        for fields in records_raw:
            reg = fields[0] if fields else ""
            meta = metadata.get(reg)
            if not meta:
                continue

            nivel  = meta.get("nivel", -1)
            parent = meta.get("parent")
            headers = headers_map.get(reg, [])

            # Pares (coluna_db, valor) vindos dos campos do registro
            col_vals: list[tuple[str, object]] = [
                (_col_db(h), v) for h, v in zip(headers, fields)
            ]

            if not col_vals:
                continue

            # fk_0000 em todos os registros que não são o próprio 0000
            if nivel != 0:
                fk_root = reg_last_id.get("0000")
                if fk_root:
                    col_vals.append(("fk_0000", fk_root))

            # fk do pai direto (quando pai não é 0000 — já coberto acima)
            if parent and parent != "0000":
                fk_parent_id = reg_last_id.get(parent)
                if fk_parent_id:
                    col_vals.append((f"fk_{parent.lower()}", fk_parent_id))

            cols         = ", ".join(c for c, _ in col_vals)
            vals         = [v for _, v in col_vals]
            placeholders = ", ".join(["%s"] * len(vals))
            tname        = f"sped_{reg.lower()}"

            cur.execute(
                f"INSERT INTO {tname} ({cols}) VALUES ({placeholders}) RETURNING id",
                vals,
            )
            reg_last_id[reg] = cur.fetchone()[0]
            total += 1

    conn.commit()
    return total


# ── Teste local ───────────────────────────────────────────────────────────────

def gerenciar_notas():
    metadata  = carregar_metadata()

    sped_file = (
        Path(__file__).parent
        / "arquivos_base"
        / "PISCOFINS_20260301_20260331_04784935000167_Original_20260415164738_3B13D02B5763C278137AB3286018AD0488132796.txt"
    )
    with open(sped_file, "rb") as f:
        records_raw = parse_sped_binary(f.read())

    records = enrich_records(records_raw, metadata)

    output = Path(__file__).parent / "sped_records.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"Gerado: {output} ({len(records)} registros)")


if __name__ == "__main__":
    gerenciar_notas()
    
