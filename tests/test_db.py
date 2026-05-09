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
