import logging
import json
import aiosqlite
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse

from devtrack import db
from devtrack.fswatcher import FsWatcher, default_roots
from devtrack.ollama import generate_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("devtrack")

state = {"session_id": None, "session_start": None}


def _local_now() -> datetime:
    """Retorna datetime actual en la zona horaria local del sistema."""
    tz = ZoneInfo("UTC")
    return datetime.now(tz=tz).astimezone().replace(tzinfo=None)


def _local_date_str() -> str:
    return _local_now().strftime("%Y-%m-%d")


async def _upsert_daily_aggregate(conn: aiosqlite.Connection, target_date: str) -> None:
    cur = await conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE DATE(start_time) = ?", (target_date,)
    )
    total_sessions = (await cur.fetchone())[0]

    cur = await conn.execute(
        "SELECT COUNT(DISTINCT file_path) FROM file_events WHERE local_date = ?", (target_date,)
    )
    total_files = (await cur.fetchone())[0]

    cur = await conn.execute(
        "SELECT COALESCE(SUM(lines_added),0), COALESCE(SUM(lines_deleted),0) "
        "FROM loc_deltas WHERE local_date = ?", (target_date,)
    )
    row = await cur.fetchone()
    total_added, total_deleted = row[0], row[1]

    cur = await conn.execute(
        "SELECT COUNT(*) FROM ai_usage WHERE DATE(timestamp) = ?", (target_date,)
    )
    total_ai = (await cur.fetchone())[0]

    await conn.execute(
        """INSERT INTO daily_aggregates
               (date, total_sessions, total_files_changed, total_lines_added, total_lines_deleted, total_ai_requests)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(date) DO UPDATE SET
               total_sessions       = excluded.total_sessions,
               total_files_changed  = excluded.total_files_changed,
               total_lines_added    = excluded.total_lines_added,
               total_lines_deleted  = excluded.total_lines_deleted,
               total_ai_requests    = excluded.total_ai_requests""",
        (target_date, total_sessions, total_files, total_added, total_deleted, total_ai),
    )


def _local_hour() -> int:
    return _local_now().hour

EXT_MAP = {
    '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript',
    '.js': 'JavaScript', '.jsx': 'JavaScript', '.go': 'Go',
    '.rs': 'Rust', '.sh': 'Shell', '.md': 'Markdown',
    '.css': 'CSS', '.scss': 'SCSS', '.html': 'HTML',
    '.json': 'JSON', '.toml': 'TOML', '.yml': 'YAML', '.yaml': 'YAML',
    '.sql': 'SQL', '.swift': 'Swift', '.kt': 'Kotlin', '.rb': 'Ruby',
}


def detect_project(fp: str) -> str | None:
    if not fp:
        return None
    p = Path(fp)
    for parent in [p.parent] + list(p.parents)[:10]:
        if (parent / '.git').is_dir():
            return parent.name
    parts = fp.split('/')
    if 'projects' in parts:
        idx = parts.index('projects')
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def detect_language(fp: str) -> str | None:
    if not fp:
        return None
    return EXT_MAP.get(Path(fp).suffix.lower())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    now = _local_now().isoformat()
    sid = await db.create_session(now)
    state["session_id"] = sid
    state["session_start"] = now
    logger.info(f"Session started: id={sid}")

    watcher = FsWatcher(default_roots(), _record_event)
    watcher.start()

    yield

    watcher.stop()
    if state["session_id"]:
        await db.end_session(state["session_id"], _local_now().isoformat())


app = FastAPI(title="devtrack", version="0.2.0", lifespan=lifespan)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DevTrack Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f12; color: #e1e4e8; font-family: 'SF Mono', 'Fira Code', monospace; padding: 24px; }
  h1 { color: #5b9cf6; font-size: 1.4rem; margin-bottom: 4px; letter-spacing: 2px; text-transform: uppercase; }
  .subtitle { color: #555; font-size: 0.75rem; margin-bottom: 28px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 28px; }
  .card { background: #161620; border: 1px solid #1e2030; border-radius: 8px; padding: 18px; }
  .card .label { color: #555; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .card .value { color: #5b9cf6; font-size: 2rem; font-weight: bold; }
  .card .unit { color: #888; font-size: 0.75rem; margin-top: 2px; }
  .section { background: #161620; border: 1px solid #1e2030; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
  .section h2 { color: #5b9cf6; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }
  canvas { max-height: 220px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  th { color: #555; text-align: left; padding: 6px 8px; border-bottom: 1px solid #1e2030; font-weight: normal; }
  td { padding: 8px 8px; border-bottom: 1px solid #111; color: #c9d1d9; }
  td:first-child { color: #5b9cf6; font-size: 0.78rem; }
  tr:last-child td { border-bottom: none; }
  .summary-box { background: #0d1117; border-left: 3px solid #5b9cf6; padding: 14px 16px; border-radius: 0 6px 6px 0;
                 font-size: 0.85rem; line-height: 1.6; color: #c9d1d9; min-height: 48px; }
  .summary-box.loading { color: #444; font-style: italic; }
  .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #5b9cf6; margin-right: 6px; }
  .green { color: #3fb950; }
  .red { color: #f85149; }
  footer { color: #333; font-size: 0.7rem; text-align: center; margin-top: 28px; }
</style>
</head>
<body>
<h1><span class="dot"></span>DevTrack</h1>
<div class="subtitle" id="subtitle">cargando...</div>

<div class="grid" id="metrics"></div>

<div class="section">
  <h2>Actividad — últimos 7 días</h2>
  <canvas id="weekChart"></canvas>
</div>

<div class="section">
  <h2>Archivos más editados hoy</h2>
  <table id="filesTable">
    <thead><tr><th>Archivo</th><th>Proyecto</th><th>Lenguaje</th><th>Edits</th></tr></thead>
    <tbody></tbody>
  </table>
</div>

<div class="section">
  <h2>Resumen del día · IA</h2>
  <div class="summary-box loading" id="aiSummary">Consultando Ollama...</div>
</div>

<footer>devtrack · auto-refresh 30s</footer>

<script>
let weekChart = null;

async function fetchJSON(url) {
  const r = await fetch(url);
  return r.json();
}

function fmtFile(path) {
  if (!path) return '?';
  const parts = path.split('/');
  return parts[parts.length - 1];
}

async function loadDashboard() {
  const [today, week, files] = await Promise.all([
    fetchJSON('/today'),
    fetchJSON('/week'),
    fetchJSON('/files'),
  ]);

  document.getElementById('subtitle').textContent =
    new Date().toLocaleString('es-MX', {weekday:'long', year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});

  // Metrics cards
  const m = document.getElementById('metrics');
  m.innerHTML = `
    <div class="card"><div class="label">Líneas escritas</div><div class="value green">+${today.lines_added ?? 0}</div><div class="unit">loc hoy</div></div>
    <div class="card"><div class="label">Líneas eliminadas</div><div class="value red">-${today.lines_deleted ?? 0}</div><div class="unit">loc hoy</div></div>
    <div class="card"><div class="label">Archivos editados</div><div class="value">${today.files_touched ?? 0}</div><div class="unit">archivos</div></div>
    <div class="card"><div class="label">Sesiones</div><div class="value">${today.sessions ?? 0}</div><div class="unit">hoy</div></div>
    <div class="card"><div class="label">Comandos Bash</div><div class="value">${today.commands_run ?? 0}</div><div class="unit">ejecutados</div></div>
  `;

  // Week chart
  const history = (week.history || []).slice(0, 7).reverse();
  const labels = history.map(r => r.local_date || r.date);
  const added = history.map(r => r.added || 0);
  const deleted = history.map(r => r.deleted || 0);

  if (weekChart) weekChart.destroy();
  const ctx = document.getElementById('weekChart').getContext('2d');
  weekChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Líneas escritas', data: added, backgroundColor: '#1f6feb', borderRadius: 4 },
        { label: 'Líneas eliminadas', data: deleted, backgroundColor: '#8b1515', borderRadius: 4 },
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#888', font: { family: 'monospace' } } } },
      scales: {
        x: { ticks: { color: '#555' }, grid: { color: '#1a1a2e' } },
        y: { ticks: { color: '#555' }, grid: { color: '#1a1a2e' } },
      }
    }
  });

  // Files table
  const tbody = document.querySelector('#filesTable tbody');
  const filesList = (files.files || []).slice(0, 8);
  if (filesList.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="color:#444;text-align:center">Sin archivos editados hoy</td></tr>';
  } else {
    tbody.innerHTML = filesList.map(f => `
      <tr>
        <td>${fmtFile(f.file_path)}</td>
        <td>${f.project || '–'}</td>
        <td>${f.language || '–'}</td>
        <td>${f.edits}</td>
      </tr>
    `).join('');
  }
}

async function loadSummary() {
  const el = document.getElementById('aiSummary');
  try {
    const r = await fetch('/api/summary');
    const data = await r.json();
    if (data.summary) {
      el.className = 'summary-box';
      el.textContent = data.summary;
    } else {
      el.className = 'summary-box';
      el.style.color = '#555';
      el.textContent = data.message || 'Instala Ollama para resúmenes con IA: https://ollama.com';
    }
  } catch {
    el.className = 'summary-box';
    el.style.color = '#555';
    el.textContent = 'Error consultando el resumen.';
  }
}

async function refresh() {
  await loadDashboard();
  await loadSummary();
}

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    tpl = _TEMPLATE_DIR / "dashboard.html"
    if tpl.exists():
        return HTMLResponse(content=tpl.read_text())
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/api/summary")
async def api_summary():
    local_today = _local_date_str()
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT COALESCE(SUM(lines_added),0) as a, COALESCE(SUM(lines_deleted),0) as d FROM loc_deltas WHERE local_date=?", (local_today,))
        row = await cur.fetchone()
        added, deleted = row["a"], row["d"]

        cur = await conn.execute("SELECT COUNT(DISTINCT file_path) as c FROM file_events WHERE local_date=? AND event_type IN ('edit','write') AND file_path != ''", (local_today,))
        files = (await cur.fetchone())["c"]

        cur = await conn.execute("SELECT COUNT(DISTINCT session_id) as c FROM file_events WHERE local_date=?", (local_today,))
        sessions = (await cur.fetchone())["c"]

        cur = await conn.execute(
            "SELECT project, SUM(lines_added) as loc FROM loc_deltas WHERE local_date=? AND project IS NOT NULL GROUP BY project ORDER BY loc DESC LIMIT 6",
            (local_today,),
        )
        projects = [{"project": r["project"], "lines": r["loc"]} async for r in cur]

        cur = await conn.execute(
            "SELECT language, SUM(lines_added) as loc FROM loc_deltas WHERE local_date=? AND language IS NOT NULL GROUP BY language ORDER BY loc DESC LIMIT 6",
            (local_today,),
        )
        languages = [{"language": r["language"], "lines": r["loc"]} async for r in cur]

    stats = {
        "lines_added": added, "lines_deleted": deleted,
        "files_touched": files, "sessions": sessions,
        "projects": projects, "languages": languages,
    }
    summary = await generate_summary(stats)
    if summary:
        return {"summary": summary}
    return {"summary": None, "message": "Instala Ollama para resúmenes con IA: https://ollama.com"}


@app.get("/health")
async def health():
    return {"status": "ok", "session_id": state["session_id"], "session_start": state["session_start"]}


async def _record_event(data: dict) -> None:
    """Persiste un evento normalizado (mismo shape que el body de POST /events).

    Compartido entre el endpoint HTTP (hooks de Claude Code) y el FsWatcher
    (cualquier otro editor/IDE: Antigravity, Vim, JetBrains, terminal, etc.)
    para que ambas fuentes alimenten las mismas tablas sin duplicar lógica.
    """
    event_type = data.get("event_type", "")
    _now = _local_now()
    timestamp = data.get("timestamp") or _now.isoformat()
    local_date = data.get("local_date") or _now.strftime("%Y-%m-%d")
    local_hour = data.get("local_hour") if data.get("local_hour") is not None else _now.hour
    file_path = data.get("file_path", "")
    details = data.get("details", {})
    project = data.get("project") or detect_project(file_path)
    language = data.get("language") or detect_language(file_path)
    session_id = state["session_id"] or 1

    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO file_events (session_id, timestamp, event_type, file_path, details, local_date, local_hour, project, language) VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, timestamp, event_type, file_path, json.dumps(details), local_date, local_hour, project, language),
        )
        if event_type == "edit":
            await conn.execute(
                "INSERT INTO loc_deltas (session_id, timestamp, file_path, lines_added, lines_deleted, local_date, local_hour, project, language) VALUES (?,?,?,?,?,?,?,?,?)",
                (session_id, timestamp, file_path, details.get("lines_added", 0), details.get("lines_deleted", 0), local_date, local_hour, project, language),
            )
        elif event_type == "write":
            await conn.execute(
                "INSERT INTO loc_deltas (session_id, timestamp, file_path, lines_added, lines_deleted, local_date, local_hour, project, language) VALUES (?,?,?,?,?,?,?,?,?)",
                (session_id, timestamp, file_path, details.get("lines", 0), 0, local_date, local_hour, project, language),
            )
        await conn.commit()
        await _upsert_daily_aggregate(conn, local_date)
        await conn.commit()


@app.post("/events")
async def post_event(request: Request):
    try:
        data = await request.json()
        await _record_event(data)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"/events error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/end")
async def end_session():
    if state["session_id"]:
        now = _local_now().isoformat()
        await db.end_session(state["session_id"], now)
        sid = await db.create_session(now)
        state["session_id"] = sid
        state["session_start"] = now
    return {"status": "ok", "new_session_id": state["session_id"]}


@app.post("/ai-usage")
async def post_ai_usage(request: Request):
    """Registra una interacción de AI (Claude Code Stop hook)."""
    try:
        data = await request.json()
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(
                """INSERT INTO ai_usage
                   (session_id, timestamp, local_date, local_hour, model,
                    prompt_chars, completion_chars, tool_calls, duration_ms, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    state["session_id"],
                    data.get("timestamp", _local_now().isoformat()),
                    data.get("local_date"),
                    data.get("local_hour"),
                    data.get("model", "claude"),
                    data.get("prompt_chars", 0),
                    data.get("completion_chars", 0),
                    data.get("tool_calls", 0),
                    data.get("duration_ms", 0),
                    data.get("source", "claude-code"),
                ),
            )
            await conn.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"/ai-usage error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _get_day_report(target_date: str) -> dict:
    """Query completo de un día dado en formato YYYY-MM-DD."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT COUNT(DISTINCT session_id) as c FROM file_events WHERE local_date=?", (target_date,))
        sessions = (await cur.fetchone())["c"]

        cur = await conn.execute("SELECT COUNT(DISTINCT file_path) as c FROM file_events WHERE local_date=? AND event_type IN ('edit','write') AND file_path != ''", (target_date,))
        files = (await cur.fetchone())["c"]

        cur = await conn.execute("SELECT COALESCE(SUM(lines_added),0) as a, COALESCE(SUM(lines_deleted),0) as d FROM loc_deltas WHERE local_date=?", (target_date,))
        row = await cur.fetchone()
        added, deleted = row["a"], row["d"]

        cur = await conn.execute("SELECT COUNT(*) as c FROM file_events WHERE local_date=? AND event_type='bash'", (target_date,))
        commands = (await cur.fetchone())["c"]

        cur = await conn.execute(
            "SELECT file_path, COUNT(*) as edits FROM file_events WHERE local_date=? AND event_type IN ('edit','write') AND file_path != '' GROUP BY file_path ORDER BY edits DESC LIMIT 5",
            (target_date,),
        )
        top_files = [{"file": r["file_path"], "edits": r["edits"]} async for r in cur]

        cur = await conn.execute(
            "SELECT project, SUM(lines_added) as loc FROM loc_deltas WHERE local_date=? AND project IS NOT NULL GROUP BY project ORDER BY loc DESC LIMIT 6",
            (target_date,),
        )
        projects = [{"project": r["project"], "lines": r["loc"]} async for r in cur]

        cur = await conn.execute(
            "SELECT language, SUM(lines_added) as loc FROM loc_deltas WHERE local_date=? AND language IS NOT NULL GROUP BY language ORDER BY loc DESC LIMIT 6",
            (target_date,),
        )
        languages = [{"language": r["language"], "lines": r["loc"]} async for r in cur]

    return {"date": target_date, "sessions": sessions, "files_touched": files,
            "lines_added": added, "lines_deleted": deleted, "commands_run": commands,
            "top_files": top_files, "projects": projects, "languages": languages}


@app.get("/export/work-sessions")
async def export_work_sessions(
    date_from: str | None = None,
    date_to: str | None = None,
    gap_minutes: int = 30,
):
    """
    Calcula bloques de trabajo reales agrupando eventos por inactividad.
    Un gap > gap_minutes entre eventos consecutivos = nueva sesión de trabajo.
    Columnas: date, session_num, start_time, end_time, duration_min,
              lines_added, lines_deleted, files_changed, bash_commands,
              top_project, top_language
    """
    async with aiosqlite.connect(db.DB_PATH) as conn:
        where = "WHERE fe.local_date IS NOT NULL"
        params: list = []
        if date_from:
            where += " AND fe.local_date >= ?"
            params.append(date_from)
        if date_to:
            where += " AND fe.local_date <= ?"
            params.append(date_to)

        cur = await conn.execute(
            f"""
            SELECT fe.timestamp, fe.local_date, fe.event_type, fe.file_path,
                   fe.project, fe.language,
                   COALESCE(ld.lines_added, 0), COALESCE(ld.lines_deleted, 0)
            FROM file_events fe
            LEFT JOIN loc_deltas ld
              ON ld.file_path = fe.file_path AND ld.timestamp = fe.timestamp
            {where}
            ORDER BY fe.timestamp
            """,
            params,
        )
        events = await cur.fetchall()

    if not events:
        return {"sessions": [], "total": 0}

    gap_seconds = gap_minutes * 60
    sessions = []
    current: dict | None = None

    for row in events:
        ts_str, local_date, etype, fpath, project, lang, added, deleted = row
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue

        if current is None or (ts - current["_last_ts"]).total_seconds() > gap_seconds:
            if current:
                current["duration_min"] = round(
                    (current["_last_ts"] - current["_start_ts"]).total_seconds() / 60, 1
                )
                sessions.append(_clean_session(current))
            current = {
                "_start_ts": ts, "_last_ts": ts,
                "date": local_date, "session_num": len(sessions) + 1,
                "start_time": ts_str, "end_time": ts_str,
                "lines_added": 0, "lines_deleted": 0,
                "files_changed": set(), "bash_commands": 0,
                "_projects": {}, "_languages": {},
            }

        current["_last_ts"] = ts
        current["end_time"] = ts_str
        current["lines_added"]   += added
        current["lines_deleted"] += deleted
        if etype == "bash":
            current["bash_commands"] += 1
        elif etype in ("edit", "write") and fpath:
            current["files_changed"].add(fpath)
        if project:
            current["_projects"][project] = current["_projects"].get(project, 0) + added
        if lang:
            current["_languages"][lang] = current["_languages"].get(lang, 0) + added

    if current:
        current["duration_min"] = round(
            (current["_last_ts"] - current["_start_ts"]).total_seconds() / 60, 1
        )
        sessions.append(_clean_session(current))

    return {"sessions": sessions, "total": len(sessions)}


def _clean_session(s: dict) -> dict:
    top_project  = max(s["_projects"],  key=s["_projects"].get)  if s["_projects"]  else ""
    top_language = max(s["_languages"], key=s["_languages"].get) if s["_languages"] else ""
    return {
        "date":          s["date"],
        "session_num":   s["session_num"],
        "start_time":    s["start_time"],
        "end_time":      s["end_time"],
        "duration_min":  s["duration_min"],
        "lines_added":   s["lines_added"],
        "lines_deleted": s["lines_deleted"],
        "files_changed": len(s["files_changed"]),
        "bash_commands": s["bash_commands"],
        "top_project":   top_project,
        "top_language":  top_language,
    }


@app.get("/today")
async def today():
    return await _get_day_report(_local_date_str())


@app.get("/report")
async def report(date: str | None = None):
    """Recupera el informe de cualquier día. ?date=YYYY-MM-DD (default: hoy)."""
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usa YYYY-MM-DD.")
        target = date
    else:
        target = _local_date_str()
    return await _get_day_report(target)


@app.get("/dates")
async def available_dates():
    """Lista todos los días con actividad registrada."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT DISTINCT local_date, SUM(lines_added) as loc, COUNT(DISTINCT file_path) as files "
            "FROM loc_deltas WHERE local_date IS NOT NULL GROUP BY local_date ORDER BY local_date DESC"
        )
        rows = [{"date": r[0], "lines_added": r[1], "files": r[2]} async for r in cur]
    return {"dates": rows}


@app.get("/export/hourly")
async def export_hourly(date_from: str | None = None, date_to: str | None = None):
    """
    Exporta datos horarios completos para análisis.
    Cada fila = una hora activa: date, hour, lines_added, lines_deleted,
    files_changed, bash_commands, edits, writes, project (top), language (top).
    """
    async with aiosqlite.connect(db.DB_PATH) as conn:
        where = "WHERE ld.local_date IS NOT NULL"
        params: list = []
        if date_from:
            where += " AND ld.local_date >= ?"
            params.append(date_from)
        if date_to:
            where += " AND ld.local_date <= ?"
            params.append(date_to)

        cur = await conn.execute(
            f"""
            SELECT ld.local_date, ld.local_hour,
                   COALESCE(SUM(ld.lines_added), 0)   AS lines_added,
                   COALESCE(SUM(ld.lines_deleted), 0) AS lines_deleted,
                   COUNT(DISTINCT ld.file_path)        AS files_changed
            FROM loc_deltas ld
            {where}
            GROUP BY ld.local_date, ld.local_hour
            ORDER BY ld.local_date, ld.local_hour
            """,
            params,
        )
        loc_rows = {(r[0], r[1]): {"lines_added": r[2], "lines_deleted": r[3], "files_changed": r[4]}
                    async for r in cur}

        fe_where = where.replace("ld.", "fe.")
        cur = await conn.execute(
            f"""
            SELECT fe.local_date, fe.local_hour,
                   SUM(CASE WHEN fe.event_type = 'bash'  THEN 1 ELSE 0 END) AS bash_cmds,
                   SUM(CASE WHEN fe.event_type = 'edit'  THEN 1 ELSE 0 END) AS edits,
                   SUM(CASE WHEN fe.event_type = 'write' THEN 1 ELSE 0 END) AS writes
            FROM file_events fe
            {fe_where}
            GROUP BY fe.local_date, fe.local_hour
            ORDER BY fe.local_date, fe.local_hour
            """,
            params,
        )
        event_rows = {(r[0], r[1]): {"bash_cmds": r[2], "edits": r[3], "writes": r[4]}
                      async for r in cur}

        # top project per hour
        cur = await conn.execute(
            f"""
            SELECT ld.local_date, ld.local_hour, ld.project, SUM(ld.lines_added) AS loc
            FROM loc_deltas ld
            {where} AND ld.project IS NOT NULL
            GROUP BY ld.local_date, ld.local_hour, ld.project
            ORDER BY ld.local_date, ld.local_hour, loc DESC
            """,
            params,
        )
        top_project: dict = {}
        async for r in cur:
            key = (r[0], r[1])
            if key not in top_project:
                top_project[key] = r[2]

        # top language per hour
        cur = await conn.execute(
            f"""
            SELECT ld.local_date, ld.local_hour, ld.language, SUM(ld.lines_added) AS loc
            FROM loc_deltas ld
            {where} AND ld.language IS NOT NULL
            GROUP BY ld.local_date, ld.local_hour, ld.language
            ORDER BY ld.local_date, ld.local_hour, loc DESC
            """,
            params,
        )
        top_language: dict = {}
        async for r in cur:
            key = (r[0], r[1])
            if key not in top_language:
                top_language[key] = r[2]

        # top 3 files per hour (by edits)
        fe_where2 = where.replace("ld.", "fe2.")
        cur = await conn.execute(
            f"""
            SELECT fe2.local_date, fe2.local_hour, fe2.file_path, COUNT(*) AS edits
            FROM file_events fe2
            {fe_where2} AND fe2.event_type IN ('edit','write') AND fe2.file_path != ''
            GROUP BY fe2.local_date, fe2.local_hour, fe2.file_path
            ORDER BY fe2.local_date, fe2.local_hour, edits DESC
            """,
            params,
        )
        top_files_by_hour: dict = {}
        async for r in cur:
            key = (r[0], r[1])
            if key not in top_files_by_hour:
                top_files_by_hour[key] = []
            if len(top_files_by_hour[key]) < 3:
                from pathlib import Path as _P
                top_files_by_hour[key].append(_P(r[2]).name)

        # ai_usage per hour
        ai_where = where.replace("ld.", "au.")
        try:
            cur = await conn.execute(
                f"""
                SELECT au.local_date, au.local_hour,
                       COUNT(*) AS interactions,
                       SUM(au.prompt_chars) AS prompt_chars,
                       SUM(au.completion_chars) AS completion_chars,
                       SUM(au.tool_calls) AS tool_calls,
                       SUM(au.duration_ms) AS duration_ms
                FROM ai_usage au
                {ai_where}
                GROUP BY au.local_date, au.local_hour
                """,
                params,
            )
            ai_rows = {(r[0], r[1]): {
                "ai_interactions": r[2], "ai_prompt_chars": r[3],
                "ai_completion_chars": r[4], "ai_tool_calls": r[5],
                "ai_duration_ms": r[6],
            } async for r in cur}
        except Exception as e:
            logger.warning("ai_usage query failed (tabla ausente o error): %s", e)
            ai_rows = {}

    all_keys = sorted(set(loc_rows) | set(event_rows))
    rows = []
    for key in all_keys:
        d, h = key
        loc  = loc_rows.get(key, {})
        evts = event_rows.get(key, {})
        ai   = ai_rows.get(key, {})
        rows.append({
            "date":                d,
            "hour":                h,
            "lines_added":         loc.get("lines_added", 0),
            "lines_deleted":       loc.get("lines_deleted", 0),
            "files_changed":       loc.get("files_changed", 0),
            "bash_commands":       evts.get("bash_cmds", 0),
            "edits":               evts.get("edits", 0),
            "writes":              evts.get("writes", 0),
            "top_project":         top_project.get(key, ""),
            "top_language":        top_language.get(key, ""),
            "top_files":           "|".join(top_files_by_hour.get(key, [])),
            "ai_interactions":     ai.get("ai_interactions", 0),
            "ai_prompt_chars":     ai.get("ai_prompt_chars", 0),
            "ai_completion_chars": ai.get("ai_completion_chars", 0),
            "ai_tool_calls":       ai.get("ai_tool_calls", 0),
            "ai_duration_ms":      ai.get("ai_duration_ms", 0),
        })
    return {"rows": rows, "total": len(rows)}


@app.post("/aggregate")
async def run_aggregate():
    """Recalcula daily_aggregates para todos los días con actividad registrada."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT DISTINCT local_date FROM loc_deltas WHERE local_date IS NOT NULL ORDER BY local_date"
        )
        dates = [r[0] async for r in cur]
        for d in dates:
            await _upsert_daily_aggregate(conn, d)
        await conn.commit()
    return {"status": "ok", "days_processed": len(dates), "dates": dates}


@app.get("/aggregate")
async def get_aggregates():
    """Devuelve el contenido actual de daily_aggregates."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM daily_aggregates ORDER BY date DESC"
        )
        rows = [dict(r) async for r in cur]
    return {"aggregates": rows}


@app.get("/files")
async def files_today():
    local_today = _local_date_str()
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT file_path, project, language, COUNT(*) as edits, MIN(timestamp) as first, MAX(timestamp) as last "
            "FROM file_events WHERE local_date=? AND event_type IN ('edit','write') AND file_path != '' "
            "GROUP BY file_path ORDER BY edits DESC",
            (local_today,),
        )
        rows = [dict(r) async for r in cur]
    return {"date": local_today, "files": rows}


@app.get("/hourly")
async def hourly():
    local_today = _local_date_str()
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT local_hour, SUM(lines_added) as loc, COUNT(*) as events FROM loc_deltas WHERE local_date=? AND local_hour IS NOT NULL GROUP BY local_hour",
            (local_today,),
        )
        data = {r["local_hour"]: {"lines": r["loc"], "events": r["events"]} async for r in cur}
    return {"date": local_today, "hourly": data}


@app.get("/streak")
async def streak():
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT DISTINCT local_date FROM file_events WHERE local_date IS NOT NULL AND event_type IN ('edit','write') ORDER BY local_date DESC"
        )
        dates = [r[0] async for r in cur]

    current = 0
    longest = 0
    run = 0
    today_local = _local_now().date()

    for i, d in enumerate(dates):
        expected = (today_local - timedelta(days=i)).isoformat()
        if d == expected:
            current += 1
        else:
            break

    # longest streak
    prev = None
    for d in sorted(dates):
        dd = date.fromisoformat(d)
        if prev and (dd - prev).days == 1:
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        prev = dd

    return {"current": current, "longest": longest, "total_days": len(dates)}


@app.get("/week")
async def week():
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT local_date, SUM(lines_added) as added, SUM(lines_deleted) as deleted, COUNT(DISTINCT file_path) as files "
            "FROM loc_deltas WHERE local_date IS NOT NULL GROUP BY local_date ORDER BY local_date DESC LIMIT 30"
        )
        rows = [dict(r) async for r in cur]
    return {"history": rows}


@app.get("/history")
async def history(limit: int = 0):
    """Retorna todo el historial de actividad. limit=0 significa sin límite."""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        query = (
            "SELECT local_date, SUM(lines_added) as added, SUM(lines_deleted) as deleted, "
            "COUNT(DISTINCT file_path) as files "
            "FROM loc_deltas WHERE local_date IS NOT NULL "
            "GROUP BY local_date ORDER BY local_date DESC"
        )
        if limit > 0:
            query += f" LIMIT {limit}"
        cur = await conn.execute(query)
        rows = [dict(r) async for r in cur]

    total_days    = len(rows)
    total_added   = sum(r["added"] or 0 for r in rows)
    total_deleted = sum(r["deleted"] or 0 for r in rows)
    total_files   = sum(r["files"] or 0 for r in rows)
    date_first    = rows[-1]["local_date"] if rows else None
    date_last     = rows[0]["local_date"] if rows else None

    return {
        "history": rows,
        "summary": {
            "total_days": total_days,
            "total_added": total_added,
            "total_deleted": total_deleted,
            "total_files": total_files,
            "date_first": date_first,
            "date_last": date_last,
        },
    }


def run():
    uvicorn.run("devtrack.main:app", host="127.0.0.1", port=17321, reload=False)


if __name__ == "__main__":
    run()
