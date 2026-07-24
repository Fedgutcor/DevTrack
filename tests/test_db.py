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
