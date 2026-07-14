import sys
import os
import aiosqlite
import logging
import socket
from pathlib import Path
from typing import Any, Dict, Optional

if sys.platform == "win32":
    DB_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "devtrack" / "devtrack.sqlite3"
else:
    DB_PATH = Path.home() / ".local" / "share" / "devtrack" / "devtrack.sqlite3"
logger = logging.getLogger("devtrack.db")

# Columnas que se agregan de forma no-destructiva a DBs pre-existentes.
# Formato: (tabla, columna, tipo_sql). Ver _migrate_columns().
_HOST_MIGRATIONS = [
    ("sessions", "host", "TEXT"),
    ("loc_deltas", "host", "TEXT"),
    ("file_events", "host", "TEXT"),
]

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_time TEXT NOT NULL,
        end_time TEXT,
        metadata TEXT,
        host TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS file_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        event_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        details TEXT,
        local_date TEXT,
        local_hour INTEGER,
        project TEXT,
        language TEXT,
        host TEXT,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS loc_deltas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        file_path TEXT NOT NULL,
        lines_added INTEGER DEFAULT 0,
        lines_deleted INTEGER DEFAULT 0,
        local_date TEXT,
        local_hour INTEGER,
        project TEXT,
        language TEXT,
        host TEXT,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        timestamp TEXT NOT NULL,
        local_date TEXT,
        local_hour INTEGER,
        model TEXT NOT NULL,
        prompt_chars INTEGER DEFAULT 0,
        completion_chars INTEGER DEFAULT 0,
        tool_calls INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        source TEXT DEFAULT 'claude'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_aggregates (
        date TEXT NOT NULL,
        total_sessions INTEGER DEFAULT 0,
        total_files_changed INTEGER DEFAULT 0,
        total_lines_added INTEGER DEFAULT 0,
        total_lines_deleted INTEGER DEFAULT 0,
        total_ai_requests INTEGER DEFAULT 0,
        PRIMARY KEY(date)
    )
    """,
]


async def _migrate_columns(db: aiosqlite.Connection) -> None:
    """Agrega columnas nuevas a DBs pre-existentes (no destructivo).

    Backfillea `host` en filas históricas con el hostname actual: esas filas
    se generaron en esta máquina antes de que existiera la dimensión host,
    así que atribuírselas a este equipo es correcto y no pierde datos.
    """
    hostname = socket.gethostname()
    for table, col, col_type in _HOST_MIGRATIONS:
        cur = await db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        if not await cur.fetchone():
            continue
        cur = await db.execute(f"PRAGMA table_info({table})")
        existing_cols = {r[1] for r in await cur.fetchall()}
        if col not in existing_cols:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            logger.info(f"Migrated: {table}.{col}")
        await db.execute(f"UPDATE {table} SET {col} = ? WHERE {col} IS NULL", (hostname,))
    await db.commit()


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        for sql in SCHEMA:
            await db.execute(sql)
        await db.commit()
        await _migrate_columns(db)
    logger.info(f"DB initialized at {DB_PATH}")


async def create_session(start_time: str, host: Optional[str] = None) -> int:
    _host = host if host is not None else socket.gethostname()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO sessions (start_time, host) VALUES (?, ?)", (start_time, _host)
        )
        await db.commit()
        return cursor.lastrowid


async def end_session(session_id: int, end_time: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE sessions SET end_time = ? WHERE id = ?", (end_time, session_id)
        )
        await db.commit()


async def insert_file_event(session_id: int, timestamp: str, event_type: str, file_path: str, details: Optional[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO file_events (session_id, timestamp, event_type, file_path, details) VALUES (?,?,?,?,?)",
            (session_id, timestamp, event_type, file_path, details),
        )
        await db.commit()


async def insert_loc_delta(session_id: int, timestamp: str, file_path: str, lines_added: int, lines_deleted: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO loc_deltas (session_id, timestamp, file_path, lines_added, lines_deleted) VALUES (?,?,?,?,?)",
            (session_id, timestamp, file_path, lines_added, lines_deleted),
        )
        await db.commit()


async def get_today_summary(today: str) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute("SELECT COUNT(*) as c FROM sessions WHERE DATE(start_time)=?", (today,))
        sessions = (await cur.fetchone())["c"]

        cur = await db.execute("SELECT COUNT(DISTINCT file_path) as c FROM file_events WHERE DATE(timestamp)=? AND language != 'Telemetry'", (today,))
        files = (await cur.fetchone())["c"]

        cur = await db.execute(
            "SELECT COALESCE(SUM(lines_added),0) as a, COALESCE(SUM(lines_deleted),0) as d FROM loc_deltas WHERE DATE(timestamp)=? AND language != 'Telemetry'",
            (today,),
        )
        row = await cur.fetchone()
        added, deleted = row["a"], row["d"]

        cur = await db.execute(
            "SELECT COALESCE(SUM(lines_added),0) as a FROM loc_deltas WHERE DATE(timestamp)=? AND language = 'Telemetry'",
            (today,),
        )
        telemetry_added = (await cur.fetchone())["a"]

        cur = await db.execute("SELECT COUNT(*) as c FROM file_events WHERE DATE(timestamp)=? AND event_type='bash'", (today,))
        commands = (await cur.fetchone())["c"]

        cur = await db.execute(
            "SELECT file_path, COUNT(*) as edits FROM file_events WHERE DATE(timestamp)=? AND event_type IN ('edit','write') AND language != 'Telemetry' GROUP BY file_path ORDER BY edits DESC LIMIT 5",
            (today,),
        )
        top_files = [{"file": r["file_path"], "edits": r["edits"]} async for r in cur]

        return {
            "date": today,
            "sessions": sessions,
            "files_touched": files,
            "lines_added": added,
            "lines_deleted": deleted,
            "telemetry_added": telemetry_added,
            "commands_run": commands,
            "top_files": top_files,
        }
