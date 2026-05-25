#!/usr/bin/env python3
"""devtrack CLI v2 — Development activity tracker with visual dashboard."""
import sys
import sqlite3
import os
import shutil
import subprocess
import httpx
from datetime import datetime, date, timedelta
from pathlib import Path

BASE = "http://127.0.0.1:17321"
DASHBOARD_URL = "http://127.0.0.1:17321"
PLIST_LABEL = "com.ultragresion.devtrack"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
DB_PATH = str(Path.home() / ".local" / "share" / "devtrack" / "devtrack.sqlite3")

# ANSI 256 colors
C  = "\x1b[38;5;51m"    # cyan neón
M  = "\x1b[38;5;201m"   # magenta
G  = "\x1b[38;5;46m"    # verde neón
G2 = "\x1b[38;5;120m"   # verde pálido
R  = "\x1b[38;5;196m"   # rojo
Y  = "\x1b[38;5;226m"   # amarillo
W  = "\x1b[38;5;255m"   # blanco
DM = "\x1b[38;5;240m"   # gris oscuro
BOLD = "\x1b[1m"
DIM  = "\x1b[2m"
RESET = "\x1b[0m"

def ansi(n):
    return f"\x1b[38;5;{n}m"


def print_logo():
    import pyfiglet
    dev_art   = pyfiglet.figlet_format("dev", font="ansi_shadow").rstrip()
    track_art = pyfiglet.figlet_format("TRACK", font="doom").rstrip()
    print()
    for line in dev_art.split("\n"):
        print(f"  {C}{line}{RESET}")
    for line in track_art.split("\n"):
        print(f"  {G}{line}{RESET}")
    print(f"  {DIM}development activity tracker  ·  v2  ·  by: ULTRAGRESION.COM{RESET}")
    print()


def api(path):
    try:
        return httpx.get(f"{BASE}{path}", timeout=3).json()
    except Exception:
        print(f"{R}✗ devtrack daemon no responde. Inicialo:{RESET}")
        print("  launchctl load ~/Library/LaunchAgents/com.devtrack.plist")
        sys.exit(1)


def api_post(path, payload=None):
    try:
        return httpx.post(f"{BASE}{path}", json=payload or {}, timeout=10).json()
    except Exception:
        print(f"{R}✗ devtrack daemon no responde. Inicialo:{RESET}")
        print("  launchctl load ~/Library/LaunchAgents/com.devtrack.plist")
        sys.exit(1)


def hbar(value, max_val, width=28, color=G):
    if max_val == 0:
        return DIM + "░" * width + RESET
    filled = min(int((value / max_val) * width), width)
    return color + "█" * filled + DIM + "░" * (width - filled) + RESET


def heatmap(weeks=8):
    """GitHub-style contribution heatmap."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    since = (date.today() - timedelta(days=weeks * 7)).isoformat()
    cur.execute(
        "SELECT local_date, SUM(lines_added) FROM loc_deltas WHERE local_date >= ? GROUP BY local_date",
        (since,),
    )
    data = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()

    today = date.today()
    start = today - timedelta(days=today.weekday() + (weeks - 1) * 7)

    rows = [[] for _ in range(7)]
    for i in range(weeks * 7):
        d = start + timedelta(days=i)
        val = data.get(d.isoformat(), 0)
        if val >= 500:
            ch, col = "█", G
        elif val >= 200:
            ch, col = "▓", G
        elif val >= 50:
            ch, col = "▒", G2
        elif val >= 1:
            ch, col = "░", G2
        else:
            ch, col = "·", DM
        rows[d.weekday()].append(col + ch + RESET)

    days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    print(f"\n{DM}  contribution graph — last {weeks} weeks{RESET}")
    for i, (label, row) in enumerate(zip(days, rows)):
        print(f"  {DIM}{label}{RESET} " + " ".join(row))
    print()


def hourly_chart(hourly_data: dict):
    """Bar chart of activity by hour."""
    if not hourly_data:
        return
    max_lines = max((v.get("lines", 0) for v in hourly_data.values()), default=1)
    print(f"{DM}  activity by hour{RESET}")
    for h in range(24):
        hstr = str(h)
        v = hourly_data.get(hstr, hourly_data.get(h, {}))
        lines = v.get("lines", 0) if isinstance(v, dict) else 0
        bar = hbar(lines, max_lines, width=20, color=C)
        marker = Y + "◀" + RESET if lines == max_lines and lines > 0 else ""
        print(f"  {DM}{h:02d}h{RESET} {bar} {DIM}{lines}{RESET}{marker}")
    print()


def cmd_today():
    h = api("/health")
    t = api("/today")
    hr = api("/hourly")
    sk = api("/streak")

    added    = t.get("lines_added", 0)
    deleted  = t.get("lines_deleted", 0)
    files    = t.get("files_touched", 0)
    commands = t.get("commands_run", 0)
    sessions = t.get("sessions", 0)
    projects  = t.get("projects", [])
    languages = t.get("languages", [])
    top_files = t.get("top_files", [])
    current_streak = sk.get("current", 0)
    longest_streak = sk.get("longest", 0)
    hourly_data    = hr.get("hourly", {})

    now_str    = datetime.now().strftime("%A %d %b · %H:%M")
    session_id = h.get("session_id", "?")

    print_logo()
    print(f"  {DIM}{now_str}{RESET}  {DM}·{RESET}  sesión #{session_id}")

    flame = "🔥" if current_streak >= 3 else "·"
    print(f"\n  {flame} streak {BOLD}{C}{current_streak}{RESET} días  {DM}·{RESET}  récord {BOLD}{longest_streak}{RESET} días\n")

    max_v = max(added, deleted, files, 1)
    print(f"  {G}+{RESET}{BOLD}{added:<6}{RESET} líneas escritas   {hbar(added, max_v)}")
    print(f"  {R}-{RESET}{BOLD}{deleted:<6}{RESET} líneas borradas   {hbar(deleted, max_v, color=R)}")
    print(f"  {C}~{RESET}{BOLD}{files:<6}{RESET} archivos tocados  {hbar(files, max_v, color=C)}")
    print(f"  {DIM}>{RESET}{DIM}{commands:<6}{RESET} comandos Bash")
    print(f"  {DIM} {sessions:<6}{RESET} sesiones\n")

    if projects:
        max_loc = max((p["lines"] for p in projects), default=1)
        print(f"  {BOLD}{M}proyectos{RESET}")
        for p in projects:
            name = (p["project"] or "?")[:18].ljust(18)
            loc  = p["lines"]
            print(f"  {DM}│{RESET} {C}{name}{RESET} {hbar(loc, max_loc, width=16)} {DIM}{loc}loc{RESET}")
        print()

    if languages:
        max_loc = max((lang["lines"] for lang in languages), default=1)
        print(f"  {BOLD}{G}lenguajes{RESET}")
        for lang in languages:
            name = (lang["language"] or "?")[:12].ljust(12)
            loc  = lang["lines"]
            print(f"  {DM}│{RESET} {G}{name}{RESET} {hbar(loc, max_loc, width=16, color=G2)} {DIM}{loc}loc{RESET}")
        print()

    if top_files:
        print(f"  {BOLD}{Y}archivos más editados{RESET}")
        for i, f in enumerate(top_files[:5], 1):
            fname = Path(f["file"]).name[:35].ljust(35) if f["file"] else "?"
            edits = f["edits"]
            print(f"  {DM}{i}.{RESET} {W}{fname}{RESET} {Y}{edits}x{RESET}")
        print()

    hourly_chart(hourly_data)
    heatmap(weeks=8)


def cmd_week():
    data    = api("/week")
    history = data.get("history", [])
    if not history:
        print(f"\n{DIM}Sin datos históricos.{RESET}\n")
        return

    max_added = max((r.get("added", 0) for r in history), default=1)
    print_logo()
    print(f"\n  {BOLD}{M}historial de actividad{RESET}\n")
    print(f"  {DIM}fecha       +lines  -lines  archivos  actividad{RESET}")
    for r in history[:14]:
        d       = r.get("local_date") or r.get("date", "?")
        added   = r.get("added", 0)
        deleted = r.get("deleted", 0)
        files   = r.get("files", 0)
        bar     = hbar(added, max_added, width=16)
        print(f"  {DM}{d}{RESET}  {G}+{added:<5}{RESET} {R}-{deleted:<5}{RESET} {C}{files:<8}{RESET} {bar}")
    print()


def cmd_files():
    data  = api("/files")
    files = data.get("files", [])
    if not files:
        print(f"\n{DIM}Sin archivos editados hoy.{RESET}\n")
        return
    print_logo()
    print(f"\n  {BOLD}{C}archivos editados hoy{RESET}\n")
    print(f"  {DIM}{'archivo':<32} {'proyecto':<16} {'lang':<12} edits{RESET}")
    for f in files:
        fname = Path(f["file_path"]).name[:31].ljust(31) if f["file_path"] else "?"
        proj  = (f.get("project") or "?")[:15].ljust(15)
        lang  = (f.get("language") or "?")[:11].ljust(11)
        edits = f["edits"]
        print(f"  {W}{fname}{RESET} {C}{proj}{RESET} {G}{lang}{RESET} {Y}{edits}x{RESET}")
    print()


def cmd_status():
    h = api("/health")
    print(f"\n  {G}✓{RESET} devtrack corriendo · sesión #{h.get('session_id')} · puerto 17321")
    print(f"  {G}✓{RESET} Dashboard {C}{DASHBOARD_URL}{RESET}")
    size = os.path.getsize(DB_PATH) / 1024 if os.path.exists(DB_PATH) else 0
    print(f"  {G}✓{RESET} SQLite {DIM}{size:.1f}KB{RESET} · {DIM}{DB_PATH}{RESET}\n")


def _server_binary() -> str | None:
    """Resolve the devtrack-server executable path."""
    binary = shutil.which("devtrack-server")
    if binary:
        return binary
    # Fallback: python -m devtrack.main via the same Python interpreter
    return sys.executable


def _write_plist(server_path: str) -> None:
    log_dir = Path.home() / "Library" / "Logs" / "devtrack"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{server_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/devtrack.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/devtrack.err</string>
</dict>
</plist>
"""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist)


def cmd_start():
    server = _server_binary()
    if not server:
        print(f"\n  {R}✗ devtrack-server no encontrado.{RESET}")
        print(f"  Instala con: {C}uv tool install .{RESET}\n")
        sys.exit(1)

    # Check if already running
    try:
        httpx.get(f"{BASE}/health", timeout=2)
        print(f"\n  {G}✓{RESET} devtrack ya está corriendo · {C}{DASHBOARD_URL}{RESET}\n")
        return
    except Exception:
        pass

    _write_plist(server)
    result = subprocess.run(
        ["launchctl", "load", "-w", str(PLIST_PATH)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"\n  {R}✗ Error al cargar LaunchAgent:{RESET}")
        print(f"  {result.stderr.strip()}\n")
        sys.exit(1)

    print(f"\n  {G}✓{RESET} devtrack iniciado como LaunchAgent")
    print(f"  {G}✓{RESET} Dashboard → {C}{DASHBOARD_URL}{RESET}")
    print(f"  {DIM}Logs: ~/Library/Logs/devtrack/devtrack.log{RESET}\n")

    # Auto-open browser
    subprocess.Popen(["open", DASHBOARD_URL])


def cmd_stop():
    if not PLIST_PATH.exists():
        print(f"\n  {Y}·{RESET} devtrack no está instalado como LaunchAgent.\n")
        return

    result = subprocess.run(
        ["launchctl", "unload", "-w", str(PLIST_PATH)],
        capture_output=True, text=True,
    )
    PLIST_PATH.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"\n  {R}✗ Error al detener:{RESET} {result.stderr.strip()}\n")
        sys.exit(1)

    print(f"\n  {G}✓{RESET} devtrack detenido y LaunchAgent eliminado.\n")


def cmd_open():
    subprocess.Popen(["open", DASHBOARD_URL])
    print(f"\n  {G}✓{RESET} Abriendo {C}{DASHBOARD_URL}{RESET}\n")


def _fetch_report(target_date: str | None) -> dict:
    path = f"/report?date={target_date}" if target_date else "/report"
    return api(path)


def cmd_report(target_date: str | None = None):
    """Muestra el informe de un día específico en formato CLI."""
    data = _fetch_report(target_date)
    added    = data.get("lines_added", 0)
    deleted  = data.get("lines_deleted", 0)
    files    = data.get("files_touched", 0)
    sessions = data.get("sessions", 0)
    commands = data.get("commands_run", 0)
    projects = data.get("projects", [])
    languages = data.get("languages", [])
    top_files = data.get("top_files", [])
    label    = data.get("date", target_date or "hoy")

    print_logo()
    print(f"  {BOLD}{M}informe · {label}{RESET}\n")

    max_v = max(added, deleted, files, 1)
    print(f"  {G}+{RESET}{BOLD}{added:<6}{RESET} líneas escritas   {hbar(added, max_v)}")
    print(f"  {R}-{RESET}{BOLD}{deleted:<6}{RESET} líneas borradas   {hbar(deleted, max_v, color=R)}")
    print(f"  {C}~{RESET}{BOLD}{files:<6}{RESET} archivos tocados  {hbar(files, max_v, color=C)}")
    print(f"  {DIM}>{RESET}{DIM}{commands:<6}{RESET} comandos  {sessions} sesiones\n")

    if projects:
        max_loc = max((p["lines"] for p in projects), default=1)
        print(f"  {BOLD}{M}proyectos{RESET}")
        for p in projects:
            name = (p["project"] or "?")[:18].ljust(18)
            print(f"  {DM}│{RESET} {C}{name}{RESET} {hbar(p['lines'], max_loc, width=16)} {DIM}{p['lines']}loc{RESET}")
        print()

    if languages:
        max_loc = max((lang_item["lines"] for lang_item in languages), default=1)
        print(f"  {BOLD}{G}lenguajes{RESET}")
        for lang in languages:
            name = (lang["language"] or "?")[:12].ljust(12)
            print(f"  {DM}│{RESET} {G}{name}{RESET} {hbar(lang['lines'], max_loc, width=16, color=G2)} {DIM}{lang['lines']}loc{RESET}")
        print()

    if top_files:
        print(f"  {BOLD}{Y}archivos{RESET}")
        for i, f in enumerate(top_files[:5], 1):
            fname = Path(f["file"]).name[:35].ljust(35) if f["file"] else "?"
            print(f"  {DM}{i}.{RESET} {W}{fname}{RESET} {Y}{f['edits']}x{RESET}")
        print()


def cmd_range(date_from: str, date_to: str | None = None):
    """Resumen agregado de un rango de fechas."""
    if not date_to:
        date_to = date.today().isoformat()

    try:
        d_from = date.fromisoformat(date_from)
        d_to   = date.fromisoformat(date_to)
        span   = (d_to - d_from).days
        if span > 30:
            print(f"\n  {Y}⚠ El rango cubre {span} días — /week solo retorna los últimos 30.{RESET}")
            print(f"  {DIM}Mostrando datos disponibles; puede haber días sin datos fuera de ese límite.{RESET}\n")
    except ValueError:
        pass

    data = api("/week")
    history = data.get("history", [])

    if not date_to:
        date_to = date.today().isoformat()

    rows = [r for r in history if date_from <= (r.get("local_date") or r.get("date", "")) <= date_to]
    if not rows:
        print(f"\n  {DIM}Sin datos entre {date_from} y {date_to}.{RESET}\n")
        return

    total_added   = sum(r.get("added", 0) for r in rows)
    total_deleted = sum(r.get("deleted", 0) for r in rows)
    total_files   = sum(r.get("files", 0) for r in rows)

    print_logo()
    print(f"  {BOLD}{M}rango · {date_from}  →  {date_to}{RESET}\n")
    print(f"  {G}+{total_added}{RESET} líneas  {R}-{total_deleted}{RESET} borradas  {C}{total_files}{RESET} archivos  {DIM}{len(rows)} días activos{RESET}\n")

    max_added = max((r.get("added", 0) for r in rows), default=1)
    print(f"  {DIM}{'fecha':<12} +lines  -lines  archivos  actividad{RESET}")
    for r in sorted(rows, key=lambda x: x.get("local_date") or x.get("date", "")):
        d       = r.get("local_date") or r.get("date", "?")
        added   = r.get("added", 0)
        deleted = r.get("deleted", 0)
        files   = r.get("files", 0)
        bar     = hbar(added, max_added, width=14)
        print(f"  {DM}{d}{RESET}  {G}+{added:<5}{RESET} {R}-{deleted:<5}{RESET} {C}{files:<8}{RESET} {bar}")
    print()


_BOX_W = 60  # ancho total del bloque ASCII


def _asciibar(value: int, max_val: int, width: int = 16) -> str:
    if max_val == 0:
        return "░" * width
    filled = round((value / max_val) * width)
    return "█" * filled + "░" * (width - filled)


def _pct(value: int, total: int) -> str:
    if total == 0:
        return " 0%"
    return f"{round(value / total * 100):2d}%"


def _box_row(left: str, right: str, width: int = _BOX_W) -> str:
    inner = width - 4  # "│ " + content + " │"
    gap   = inner - len(left) - len(right)
    return f"│ {left}{' ' * max(gap, 1)}{right} │"


def _section(title: str, rows: list[str]) -> list[str]:
    w = _BOX_W
    out = [
        f"├{'─' * (w - 2)}┤",
        f"│ {title.upper():<{w - 4}} │",
        f"├{'─' * (w - 2)}┤",
    ]
    out += rows
    return out


def _day_report_md(data: dict) -> list[str]:
    """Informe de un día en ASCII box art — ancho fijo, sin tablas markdown."""
    label    = data.get("date", "?")
    added    = data.get("lines_added", 0)
    deleted  = data.get("lines_deleted", 0)
    files    = data.get("files_touched", 0)
    commands = data.get("commands_run", 0)
    sessions = data.get("sessions", 0)
    w = _BOX_W

    out = [
        "",
        f"┌{'─' * (w - 2)}┐",
        f"│ DevTrack · {label:<{w - 16}} │",
        f"├{'─' * (w - 2)}┤",
        _box_row(f"+{added:,} escritas", f"−{deleted:,} eliminadas"),
        _box_row(f"{files} archivos", f"{sessions} sesiones · {commands} cmds"),
    ]

    projects = data.get("projects", [])
    if projects:
        max_loc = max((p["lines"] for p in projects), default=1)
        total   = sum(p["lines"] for p in projects)
        out += _section("proyectos", [])
        for p in projects:
            name  = (p["project"] or "?")[:18].ljust(18)
            loc   = f"{p['lines']:>5,}"
            bar   = _asciibar(p["lines"], max_loc, width=12)
            pct   = _pct(p["lines"], total)
            out.append(f"│  {name}  {loc}  {bar}  {pct}  │")

    langs = data.get("languages", [])
    if langs:
        max_loc = max((l["lines"] for l in langs), default=1)
        total   = sum(l["lines"] for l in langs)
        out += _section("lenguajes", [])
        for lang in langs:
            name = (lang["language"] or "?")[:14].ljust(14)
            loc  = f"{lang['lines']:>5,}"
            bar  = _asciibar(lang["lines"], max_loc, width=12)
            pct  = _pct(lang["lines"], total)
            out.append(f"│  {name}  {loc}  {bar}  {pct}  │")

    top = data.get("top_files", [])
    if top:
        max_edits = max((f["edits"] for f in top), default=1)
        out += _section("archivos más editados", [])
        for i, f in enumerate(top, 1):
            fname = (Path(f["file"]).name if f["file"] else "?")[:28].ljust(28)
            edits = f"{f['edits']:>3}"
            bar   = _asciibar(f["edits"], max_edits, width=10)
            out.append(f"│  {i}. {fname}  {edits}  {bar}  │")

    out.append(f"└{'─' * (w - 2)}┘")
    out.append("")
    return out


def cmd_all(limit: int = 0):
    """Muestra el historial completo de actividad desde el primer registro."""
    data = api(f"/history{'?limit=' + str(limit) if limit else ''}")
    history = data.get("history", [])
    summary = data.get("summary", {})

    if not history:
        print(f"\n  {DIM}Sin datos registrados.{RESET}\n")
        return

    print_logo()
    first  = summary.get("date_first", "?")
    last   = summary.get("date_last", "?")
    days   = summary.get("total_days", len(history))
    added  = summary.get("total_added", sum(r.get("added", 0) for r in history))
    deleted = summary.get("total_deleted", sum(r.get("deleted", 0) for r in history))

    print(f"  {BOLD}{M}historial completo · {first}  →  {last}{RESET}\n")
    print(f"  {G}+{added:,}{RESET} líneas  {R}-{deleted:,}{RESET} borradas  {BOLD}{days}{RESET} días activos\n")

    max_added = max((r.get("added", 0) for r in history), default=1)
    rows = sorted(history, key=lambda x: x.get("local_date", ""))
    print(f"  {DIM}{'fecha':<12}  {'+lines':>7}  {'-lines':>7}  {'archivos':>8}  actividad{RESET}")
    for r in rows:
        d       = r.get("local_date", "?")
        a       = r.get("added", 0)
        dl      = r.get("deleted", 0)
        files   = r.get("files", 0)
        bar     = hbar(a, max_added, width=18)
        print(f"  {DM}{d}{RESET}  {G}{a:>7,}{RESET}  {R}{dl:>7,}{RESET}  {C}{files:>8}{RESET}  {bar}")
    print()


def _build_params(date_from: str | None, date_to: str | None, extra: str = "") -> str:
    parts = []
    if date_from:
        parts.append(f"date_from={date_from}")
    if date_to:
        parts.append(f"date_to={date_to}")
    if extra:
        parts.append(extra)
    return ("?" + "&".join(parts)) if parts else ""


def cmd_export_hourly(date_from: str | None = None, date_to: str | None = None):
    """Exporta datos horarios completos en CSV para análisis de datos."""
    import csv as _csv
    import io as _io

    data = api(f"/export/hourly{_build_params(date_from, date_to)}")
    rows = data.get("rows", [])
    fields = [
        "date", "hour", "lines_added", "lines_deleted", "files_changed",
        "bash_commands", "edits", "writes", "top_project", "top_language", "top_files",
        "ai_interactions", "ai_prompt_chars", "ai_completion_chars",
        "ai_tool_calls", "ai_duration_ms",
    ]
    buf = _io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    print(buf.getvalue(), end="")


def cmd_export_sessions(date_from: str | None = None, date_to: str | None = None, gap: int = 30):
    """Exporta bloques de trabajo reales (inactividad > gap minutos = nueva sesión)."""
    import csv as _csv
    import io as _io

    data = api(f"/export/work-sessions{_build_params(date_from, date_to, f'gap_minutes={gap}')}")
    rows = data.get("sessions", [])
    fields = [
        "date", "session_num", "start_time", "end_time", "duration_min",
        "lines_added", "lines_deleted", "files_changed", "bash_commands",
        "top_project", "top_language",
    ]
    buf = _io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    print(buf.getvalue(), end="")


def cmd_export(target_date: str | None = None, fmt: str = "md", scope: str = "day"):
    """Exporta informes a markdown, JSON o CSV (stdout, pipeable).

    scope: 'day' | 'week' | 'all'
    """
    import json as _json
    import csv as _csv
    import io as _io

    def _to_csv(rows: list[dict], fields: list[str]) -> str:
        buf = _io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()

    if scope == "all":
        dates_data = api("/dates").get("dates", [])
        if not dates_data:
            print("# DevTrack — sin datos registrados")
            return
        all_days = [_fetch_report(d["date"]) for d in dates_data]
        if fmt == "json":
            print(_json.dumps(all_days, indent=2, ensure_ascii=False))
            return
        if fmt == "csv":
            rows = [
                {
                    "date": d.get("date", ""),
                    "lines_added": d.get("lines_added", 0),
                    "lines_deleted": d.get("lines_deleted", 0),
                    "files_changed": d.get("files_touched", 0),
                    "sessions": d.get("sessions", 0),
                }
                for d in all_days
            ]
            print(_to_csv(rows, ["date", "lines_added", "lines_deleted", "files_changed", "sessions"]), end="")
            return
        total_added   = sum(d.get("lines_added", 0) for d in all_days)
        total_deleted = sum(d.get("lines_deleted", 0) for d in all_days)
        total_files   = sum(d.get("files_touched", 0) for d in all_days)
        first = dates_data[-1]["date"] if dates_data else "?"
        last  = dates_data[0]["date"] if dates_data else "?"
        out = [
            "# DevTrack — Historial completo",
            "",
            f"> Período: **{first}** → **{last}** · **{len(all_days)}** días activos",
            "",
            f"> **+{total_added:,}** líneas escritas · **−{total_deleted:,}** eliminadas · **{total_files:,}** archivos tocados",
            "", "---", "",
        ]
        for d in all_days:
            out += _day_report_md(d)
        print("\n".join(out))
        return

    if scope == "week":
        week_data = api("/week").get("history", [])[:7]
        if not week_data:
            print("# DevTrack — sin datos esta semana")
            return
        if fmt == "json":
            print(_json.dumps(week_data, indent=2, ensure_ascii=False))
            return
        if fmt == "csv":
            rows = [
                {
                    "date": r.get("local_date") or r.get("date", ""),
                    "lines_added": r.get("added", 0),
                    "lines_deleted": r.get("deleted", 0),
                    "files_changed": r.get("files", 0),
                }
                for r in sorted(week_data, key=lambda x: x.get("local_date") or x.get("date", ""))
            ]
            print(_to_csv(rows, ["date", "lines_added", "lines_deleted", "files_changed"]), end="")
            return
        sorted_week = sorted(week_data, key=lambda x: x.get("local_date") or x.get("date", ""))
        total_added   = sum(r.get("added", 0) for r in sorted_week)
        total_deleted = sum(r.get("deleted", 0) for r in sorted_week)
        total_files   = sum(r.get("files", 0) for r in sorted_week)
        max_added     = max((r.get("added", 0) for r in sorted_week), default=1)
        w = _BOX_W
        out = [
            "# DevTrack — Última semana",
            "",
            f"┌{'─' * (w - 2)}┐",
            f"│ {'DevTrack · última semana':<{w - 4}} │",
            f"├{'─' * (w - 2)}┤",
            _box_row(f"+{total_added:,} escritas", f"−{total_deleted:,} eliminadas"),
            _box_row(f"{total_files} archivos totales", f"{len(sorted_week)} días activos"),
            f"├{'─' * (w - 2)}┤",
            f"│  {'FECHA':<12}  {'  +LOC':>7}  {'  -LOC':>7}  {'FILES':>5}  {'ACTIVIDAD':<16} │",
            f"│  {'─'*12}  {'─'*7}  {'─'*7}  {'─'*5}  {'─'*16} │",
        ]
        for r in sorted_week:
            d       = r.get("local_date") or r.get("date", "?")
            added   = r.get("added", 0)
            deleted = r.get("deleted", 0)
            files   = r.get("files", 0)
            bar     = _asciibar(added, max_added, width=16)
            out.append(f"│  {d:<12}  {added:>7,}  {deleted:>7,}  {files:>5}  {bar} │")
        out.append(f"└{'─' * (w - 2)}┘")
        print("\n".join(out))
        return

    # scope == "day" (default)
    data = _fetch_report(target_date)
    if fmt == "json":
        print(_json.dumps(data, indent=2, ensure_ascii=False))
        return
    if fmt == "csv":
        rows = [{
            "date": data.get("date", target_date or date.today().isoformat()),
            "lines_added": data.get("lines_added", 0),
            "lines_deleted": data.get("lines_deleted", 0),
            "files_changed": data.get("files_touched", 0),
            "sessions": data.get("sessions", 0),
        }]
        print(_to_csv(rows, ["date", "lines_added", "lines_deleted", "files_changed", "sessions"]), end="")
        return
    label = data.get("date", target_date or date.today().isoformat())
    out = [f"# DevTrack — {label}", ""] + _day_report_md(data)
    print("\n".join(out))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"

    if cmd in ("today", "t", ""):
        cmd_today()
    elif cmd in ("week", "w"):
        cmd_week()
    elif cmd in ("files", "f"):
        cmd_files()
    elif cmd in ("status", "s"):
        cmd_status()
    elif cmd == "start":
        cmd_start()
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "open":
        cmd_open()
    elif cmd in ("report", "r"):
        target = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_report(target)
    elif cmd in ("range",):
        if len(sys.argv) < 3:
            print(f"  {R}Uso: devtrack range <desde> [hasta]{RESET}  (formato YYYY-MM-DD)")
            sys.exit(1)
        date_from = sys.argv[2]
        date_to   = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_range(date_from, date_to)
    elif cmd in ("export", "x"):
        target   = None
        fmt      = "md"
        scope    = "day"
        hourly   = False
        sessions = False
        date_to  = None
        gap_min  = None
        for a in sys.argv[2:]:
            if a in ("--json", "-j"):
                fmt = "json"
            elif a in ("--csv", "-c"):
                fmt = "csv"
            elif a in ("--week", "-w"):
                scope = "week"
            elif a in ("--all", "-a"):
                scope = "all"
            elif a in ("--hourly", "-h"):
                hourly = True
            elif a in ("--sessions",):
                sessions = True
            elif a.startswith("--gap="):
                gap_min = a.split("=", 1)[1]
            elif not a.startswith("-"):
                if target is None:
                    target = a
                else:
                    date_to = a
        if hourly:
            cmd_export_hourly(target, date_to)
        elif sessions:
            gap = int(gap_min) if gap_min else 30
            cmd_export_sessions(target, date_to, gap)
        else:
            cmd_export(target, fmt, scope)
    elif cmd in ("all", "a"):
        limit = 0
        for arg in sys.argv[2:]:
            if arg.startswith("--limit="):
                limit = int(arg.split("=", 1)[1])
            elif arg.isdigit():
                limit = int(arg)
        cmd_all(limit)
    elif cmd in ("aggregate", "agg"):
        result = api_post("/aggregate")
        n = result.get("days_processed", 0)
        print(f"  {G}✓{RESET} daily_aggregates actualizado — {BOLD}{n}{RESET} días procesados")
    elif cmd == "help":
        print(f"\n  {BOLD}devtrack{RESET} — development activity tracker\n")
        print(f"  {C}devtrack{RESET}                        resumen del día")
        print(f"  {C}devtrack week{RESET}                   historial 30 días")
        print(f"  {C}devtrack files{RESET}                  archivos editados hoy")
        print(f"  {C}devtrack report <YYYY-MM-DD>{RESET}    informe de un día específico")
        print(f"  {C}devtrack range <desde> [hasta]{RESET}  resumen de un rango de fechas")
        print(f"  {C}devtrack export [fecha] [--json|--csv]{RESET}  exporta día a markdown, JSON o CSV")
        print(f"  {C}devtrack export --week [--json|--csv]{RESET}   exporta última semana")
        print(f"  {C}devtrack export --all  [--json|--csv]{RESET}   exporta historial completo")
        print(f"  {C}devtrack export --hourly [desde] [hasta]{RESET} exporta datos por hora (CSV)")
        print(f"  {DM}  devtrack export --hourly > hourly.csv{RESET}")
        print(f"  {DM}  devtrack export --hourly 2026-05-12 2026-05-18 > rango.csv{RESET}")
        print(f"  {C}devtrack all{RESET}                    historial completo (todos los registros)")
        print(f"  {C}devtrack all --limit=N{RESET}          últimos N días del historial")
        print(f"  {C}devtrack status{RESET}                 estado del daemon")
        print(f"  {C}devtrack start{RESET}                  inicia el daemon")
        print(f"  {C}devtrack stop{RESET}                   detiene el daemon")
        print(f"  {C}devtrack open{RESET}                   abre el dashboard en el browser\n")
        print(f"  {DIM}Ejemplos:{RESET}")
        print(f"  {DM}devtrack report 2026-05-10{RESET}")
        print(f"  {DM}devtrack range 2026-05-01 2026-05-11{RESET}")
        print(f"  {DM}devtrack export 2026-05-10 > informe.md{RESET}")
        print(f"  {DM}devtrack export --week > semana.md{RESET}")
        print(f"  {DM}devtrack export --all > historial.md{RESET}")
        print(f"  {DM}devtrack export --all --json | jq '.[] | .date'{RESET}\n")
    else:
        print(f"  {R}Comando desconocido: {cmd}{RESET}  —  usa {C}devtrack help{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
