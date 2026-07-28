import socket

import pytest
import aiosqlite
from unittest.mock import patch

import devtrack.db as db_module


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    with patch.object(db_module, "DB_PATH", db_path):
        yield db_path


@pytest.mark.asyncio
async def test_schema_creates_all_tables(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in await cur.fetchall()}

    assert "sessions" in tables
    assert "file_events" in tables
    assert "loc_deltas" in tables
    assert "ai_usage" in tables
    assert "daily_aggregates" in tables


@pytest.mark.asyncio
async def test_file_events_has_new_columns(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(file_events)")
        columns = {r[1] for r in await cur.fetchall()}

    assert "local_date" in columns
    assert "local_hour" in columns
    assert "project" in columns
    assert "language" in columns


@pytest.mark.asyncio
async def test_loc_deltas_has_new_columns(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(loc_deltas)")
        columns = {r[1] for r in await cur.fetchall()}

    assert "local_date" in columns
    assert "local_hour" in columns
    assert "project" in columns
    assert "language" in columns


@pytest.mark.asyncio
async def test_create_and_end_session(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()
        sid = await db_module.create_session("2025-01-01T00:00:00")
        assert isinstance(sid, int)
        assert sid > 0
        await db_module.end_session(sid, "2025-01-01T01:00:00")

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("SELECT end_time FROM sessions WHERE id=?", (sid,))
        row = await cur.fetchone()
    assert row[0] == "2025-01-01T01:00:00"


# ─── Dimensión host (flota multi-máquina) ──────────────────────────────────


@pytest.mark.asyncio
async def test_sessions_has_host_column(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(sessions)")
        columns = {r[1] for r in await cur.fetchall()}

    assert "host" in columns


@pytest.mark.asyncio
async def test_loc_deltas_has_host_column(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(loc_deltas)")
        columns = {r[1] for r in await cur.fetchall()}

    assert "host" in columns


@pytest.mark.asyncio
async def test_file_events_has_host_column(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(file_events)")
        columns = {r[1] for r in await cur.fetchall()}

    assert "host" in columns


@pytest.mark.asyncio
async def test_create_session_records_current_hostname(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()
        sid = await db_module.create_session("2025-01-01T00:00:00")

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("SELECT host FROM sessions WHERE id=?", (sid,))
        row = await cur.fetchone()

    assert row[0] == socket.gethostname()


@pytest.mark.asyncio
async def test_create_session_accepts_explicit_host_override(tmp_db):
    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()
        sid = await db_module.create_session("2025-01-01T00:00:00", host="remote-host")

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("SELECT host FROM sessions WHERE id=?", (sid,))
        row = await cur.fetchone()

    assert row[0] == "remote-host"


@pytest.mark.asyncio
async def test_migration_backfills_existing_null_host_rows(tmp_db):
    """DB pre-existente (schema viejo sin `host`) no debe perder datos ni
    quedar con host=NULL tras migrar — se backfillea con el hostname actual."""
    # Simula una DB del Mac creada ANTES de esta migración: schema viejo,
    # sin columna host, con datos históricos reales.
    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "start_time TEXT NOT NULL, end_time TEXT, metadata TEXT)"
        )
        await conn.execute(
            "CREATE TABLE loc_deltas (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id INTEGER NOT NULL, timestamp TEXT NOT NULL, file_path TEXT NOT NULL, "
            "lines_added INTEGER DEFAULT 0, lines_deleted INTEGER DEFAULT 0, "
            "local_date TEXT, local_hour INTEGER, project TEXT, language TEXT)"
        )
        await conn.execute(
            "INSERT INTO sessions (start_time) VALUES ('2025-06-01T00:00:00')"
        )
        await conn.execute(
            "INSERT INTO loc_deltas (session_id, timestamp, file_path, lines_added, lines_deleted, local_date) "
            "VALUES (1, '2025-06-01T00:00:00', 'foo.py', 42, 3, '2025-06-01')"
        )
        await conn.commit()

    with patch.object(db_module, "DB_PATH", tmp_db):
        await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM sessions WHERE id=1")
        session_row = await cur.fetchone()
        cur = await conn.execute("SELECT * FROM loc_deltas WHERE id=1")
        loc_row = await cur.fetchone()

    # Datos históricos preservados intactos
    assert session_row["start_time"] == "2025-06-01T00:00:00"
    assert loc_row["lines_added"] == 42
    assert loc_row["lines_deleted"] == 3
    # host backfilleado, no NULL
    assert session_row["host"] == socket.gethostname()
    assert loc_row["host"] == socket.gethostname()


async def test_migration_agrega_columnas_faltantes_a_ai_usage(tmp_db):
    """Una `ai_usage` con el schema viejo debe recibir local_date/local_hour/tool_calls.

    Reproduce el estado REAL de kabuteri el 2026-07-28: la tabla en disco tenía
    8 columnas mientras SCHEMA declaraba 11. `CREATE TABLE IF NOT EXISTS` no
    migra una tabla que ya existe, y `_migrate_columns` solo cubría `host` en
    otras tres tablas — así que cada `POST /ai-usage` reventaba con
    "no such column: local_date" y devolvía HTTP 500. La tabla llevaba 0 filas
    desde que esas columnas entraron al código.
    """
    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "CREATE TABLE ai_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id INTEGER, timestamp TEXT NOT NULL, model TEXT NOT NULL, "
            "prompt_chars INTEGER DEFAULT 0, completion_chars INTEGER DEFAULT 0, "
            "duration_ms INTEGER DEFAULT 0, source TEXT DEFAULT 'claude')"
        )
        await conn.commit()

    await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(ai_usage)")
        cols = {r[1] for r in await cur.fetchall()}

    for col in ("local_date", "local_hour", "tool_calls"):
        assert col in cols, f"falta {col} en ai_usage tras migrar"


async def test_insert_real_en_ai_usage_migrada_no_revienta(tmp_db):
    """Tras migrar, el INSERT exacto que hace POST /ai-usage debe funcionar.

    El test de arriba prueba que las columnas EXISTEN; este prueba que la
    escritura real pasa. Es la diferencia entre "la columna está" y "el
    endpoint escribe", que es lo que estaba roto.
    """
    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "CREATE TABLE ai_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id INTEGER, timestamp TEXT NOT NULL, model TEXT NOT NULL, "
            "prompt_chars INTEGER DEFAULT 0, completion_chars INTEGER DEFAULT 0, "
            "duration_ms INTEGER DEFAULT 0, source TEXT DEFAULT 'claude')"
        )
        await conn.commit()

    await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            """INSERT INTO ai_usage
               (session_id, timestamp, local_date, local_hour, model,
                prompt_chars, completion_chars, tool_calls, duration_ms, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (1, "2026-07-28T10:00:00", "2026-07-28", 10, "claude-opus-5",
             1000, 500, 7, 1234, "claude-code"),
        )
        await conn.commit()
        cur = await conn.execute("SELECT local_date, tool_calls FROM ai_usage")
        fila = await cur.fetchone()

    assert fila == ("2026-07-28", 7)


async def test_columnas_nuevas_de_ai_usage_no_se_rellenan_con_hostname(tmp_db):
    """El backfill de hostname es exclusivo de `host`.

    `_migrate_columns` hacía `UPDATE {table} SET {col} = hostname WHERE {col}
    IS NULL` para toda columna migrada. Aplicado a local_date/local_hour/
    tool_calls llenaría datos numéricos y de fecha con el nombre de la máquina.
    """
    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "CREATE TABLE ai_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id INTEGER, timestamp TEXT NOT NULL, model TEXT NOT NULL, "
            "prompt_chars INTEGER DEFAULT 0, completion_chars INTEGER DEFAULT 0, "
            "duration_ms INTEGER DEFAULT 0, source TEXT DEFAULT 'claude')"
        )
        await conn.execute(
            "INSERT INTO ai_usage (timestamp, model) VALUES ('2026-07-01T00:00:00','claude')"
        )
        await conn.commit()

    await db_module.init_db()

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("SELECT local_date, local_hour, tool_calls FROM ai_usage")
        fila = await cur.fetchone()

    hostname = socket.gethostname()
    assert fila[0] != hostname, "local_date no debe backfillearse con el hostname"
    assert fila[1] != hostname, "local_hour no debe backfillearse con el hostname"
    assert fila[2] != hostname, "tool_calls no debe backfillearse con el hostname"
