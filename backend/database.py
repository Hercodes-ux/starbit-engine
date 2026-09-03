"""
Handles turning an uploaded file (CSV, SQLite .db, or DuckDB .duckdb)
into a queryable in-memory DuckDB connection scoped to one session.

Why DuckDB: it can query CSV files directly, attach SQLite files
natively, and speaks standard SQL -- which means Databit (the SQL
agent) only ever needs to know one dialect no matter what the user
uploads.
"""
import os
import sqlite3
import uuid
import duckdb
import pandas as pd

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# session_id -> live duckdb connection
_connections: dict[str, duckdb.DuckDBPyConnection] = {}
# session_id -> {"tables": [...], "schema_text": "..."}
_schemas: dict[str, dict] = {}


def _describe_schema(con: duckdb.DuckDBPyConnection) -> dict:
    """Builds a human/LLM-readable schema summary of every table."""
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main'"
    ).fetchall()
    table_names = [t[0] for t in tables]

    lines = []
    for name in table_names:
        cols = con.execute(f"PRAGMA table_info('{name}')").fetchall()
        col_desc = ", ".join(f"{c[1]} ({c[2]})" for c in cols)
        row_count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        lines.append(f"- {name} [{row_count} rows]: {col_desc}")

    return {
        "tables": table_names,
        "schema_text": "\n".join(lines) if lines else "(no tables found)",
    }


def load_file_for_session(session_id: str, filename: str, raw_bytes: bytes) -> dict:
    """
    Persists the upload to disk, loads it into a fresh DuckDB connection
    for this session, and returns a schema summary.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    safe_name = f"{uuid.uuid4().hex}_{filename}"
    path = os.path.join(UPLOAD_DIR, safe_name)
    with open(path, "wb") as f:
        f.write(raw_bytes)

    con = duckdb.connect(database=":memory:")

    if ext == "csv":
        df = pd.read_csv(path)
        con.register("temp_df", df)
        table_name = filename.rsplit(".", 1)[0].replace(" ", "_").replace("-", "_")
        con.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM temp_df')
        con.unregister("temp_df")
    elif ext in ("db", "sqlite", "sqlite3"):
        # Read via Python's built-in sqlite3 + pandas rather than DuckDB's
        # sqlite extension -- that extension is fetched over the network on
        # first use, which is a needless external dependency (and fails
        # outright in network-restricted environments). This keeps the
        # whole upload path fully offline after `pip install`.
        sqlite_con = sqlite3.connect(path)
        table_names = [
            row[0] for row in sqlite_con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for t in table_names:
            df = pd.read_sql_query(f'SELECT * FROM "{t}"', sqlite_con)
            con.register("temp_df", df)
            con.execute(f'CREATE TABLE "{t}" AS SELECT * FROM temp_df')
            con.unregister("temp_df")
        sqlite_con.close()
    elif ext == "duckdb":
        con.close()
        con = duckdb.connect(database=path, read_only=True)
    else:
        raise ValueError(f"Unsupported file type: .{ext}. Use .csv, .db/.sqlite, or .duckdb")

    _connections[session_id] = con
    schema = _describe_schema(con)
    _schemas[session_id] = schema
    return schema


def get_connection(session_id: str) -> duckdb.DuckDBPyConnection:
    if session_id not in _connections:
        raise KeyError("No dataset uploaded yet for this session.")
    return _connections[session_id]


def get_schema(session_id: str) -> dict:
    if session_id not in _schemas:
        raise KeyError("No dataset uploaded yet for this session.")
    return _schemas[session_id]


def run_readonly_query(session_id: str, sql: str) -> pd.DataFrame:
    """
    Executes SQL against the session's dataset. Only SELECT / WITH
    statements are allowed -- Databit should never mutate uploaded data.
    """
    normalized = sql.strip().lstrip("(").strip().lower()
    if not (normalized.startswith("select") or normalized.startswith("with")):
        raise ValueError("Only SELECT queries are permitted.")
    con = get_connection(session_id)
    return con.execute(sql).fetchdf()
