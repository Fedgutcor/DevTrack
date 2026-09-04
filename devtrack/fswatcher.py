"""Universal filesystem watcher — captura ediciones de cualquier editor/IDE
(Antigravity, Vim, JetBrains, terminal, etc.), no solo Claude Code.

Corre un watchdog.Observer en un hilo de SO y empuja eventos ya normalizados
a una cola thread-safe que un task async drena hacia la misma ruta de
persistencia que usa POST /events.
"""
import difflib
import hashlib
import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger("devtrack.fswatch")

IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    "target", ".next", ".nuxt", "coverage", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "site-packages", ".cache", ".idea", ".vscode", "vendor",
    ".turbo", ".parcel-cache", ".pnpm-store", "tmp",
}

TELEMETRY_DIRS = {"data", "logs", "log", "out", "builds", "temp"}

EXT_MAP = {
    '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript',
    '.js': 'JavaScript', '.jsx': 'JavaScript', '.go': 'Go',
    '.rs': 'Rust', '.sh': 'Shell', '.md': 'Markdown',
    '.css': 'CSS', '.scss': 'SCSS', '.html': 'HTML',
    '.json': 'JSON', '.toml': 'TOML', '.yml': 'YAML', '.yaml': 'YAML',
    '.sql': 'SQL', '.swift': 'Swift', '.kt': 'Kotlin', '.rb': 'Ruby',
}

DEBOUNCE_SECONDS = 2.0
# Por encima de este tamaño no se calcula un diff línea a línea (costoso en el
# handler), pero el archivo SIGUE registrándose: se compara por digest y se
# reporta el delta de conteo de líneas. Descartarlo lo volvía invisible para
# siempre — los labs HTML autónomos pesan 3-5 MB.
MAX_DIFF_BYTES = 2_000_000
# Un on_created de FSEvents puede llegar por un archivo preexistente (coalescing).
# Solo se cuenta como creación real si el archivo se tocó hace muy poco.
CREATION_MAX_AGE_SECONDS = 60.0
READ_CHUNK = 1 << 20
#: Cuánto se reusa la lista de archivos versionados de un directorio. Una
#: operación de VCS materializa cientos de archivos en segundos; sin caché
#: sería un subproceso git por archivo.
VCS_CACHE_SECONDS = 10.0
GIT_TIMEOUT = 5.0


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS or part.endswith(".egg-info") for part in path.parts)


def _is_telemetry(path: Path) -> bool:
    return any(part in TELEMETRY_DIRS for part in path.parts)


@dataclass(frozen=True)
class _Snapshot:
    """Estado conocido de un archivo.

    `lines` es None cuando el archivo supera MAX_DIFF_BYTES: ahí solo se
    conservan el digest y el conteo de líneas, que alcanzan para saber si
    cambió y cuánto creció.
    """

    digest: str
    n_lines: int
    lines: list[str] | None


def _real_diff(old_lines: list[str], new_lines: list[str]) -> tuple[int, int]:
    added = deleted = 0
    for line in difflib.unified_diff(old_lines, new_lines, n=0):
        if line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            deleted += 1
    return added, deleted


class _Handler(FileSystemEventHandler):
    """Filtra ruido, debounce por archivo, y calcula diff real vs. última versión vista."""

    def __init__(self, out_queue: "queue.Queue[dict]"):
        self._queue = out_queue
        self._last_seen: dict[str, float] = {}
        self._cache: dict[str, _Snapshot] = {}
        self._vcs_cache: dict[str, tuple[float, set[str]]] = {}
        self._lock = threading.Lock()

    def _should_track(self, path_str: str) -> str | None:
        p = Path(path_str)
        if _is_ignored(p):
            return None
        ext = p.suffix.lower()
        if ext not in EXT_MAP:
            return None
        if _is_telemetry(p):
            return "Telemetry"
        return EXT_MAP.get(ext)

    def _debounced(self, path_str: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last_seen.get(path_str, 0.0)
            self._last_seen[path_str] = now
        return (now - last) < DEBOUNCE_SECONDS

    def _read_snapshot(self, path_str: str) -> _Snapshot | None:
        """Devuelve el estado del archivo, o None si no se pudo leer.

        Un archivo grande no se descarta: se lee por chunks para obtener
        digest y conteo de líneas sin cargarlo entero como lista de strings.
        """
        try:
            if os.path.getsize(path_str) > MAX_DIFF_BYTES:
                digest = hashlib.blake2b(digest_size=16)
                n_lines = 0
                tail_nl = True
                with open(path_str, "rb") as f:
                    while chunk := f.read(READ_CHUNK):
                        digest.update(chunk)
                        n_lines += chunk.count(b"\n")
                        tail_nl = chunk.endswith(b"\n")
                if not tail_nl:
                    n_lines += 1  # última línea sin salto final
                return _Snapshot(digest.hexdigest(), n_lines, None)

            with open(path_str, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            lines = content.splitlines()
            digest = hashlib.blake2b(content.encode("utf-8"), digest_size=16).hexdigest()
            return _Snapshot(digest, len(lines), lines)
        except OSError:
            return None

    def _es_versionado(self, path_str: str) -> bool:
        """¿El archivo ya está en el índice de git de su repo?

        Un `git worktree add`, un `clone` o un `checkout` materializan archivos
        que el repo YA contiene: aparecen como creados y no son trabajo nuevo.
        Contarlos infló `command-center-wt` en +80.059 LOC el 2026-09-03.

        Se pregunta por directorio y se cachea: en una ráfaga de checkout eso
        es un subproceso por carpeta y no uno por archivo. Fuera de un repo la
        respuesta es False — sin repo no hay checkout posible, así que un
        archivo suelto se cuenta como trabajo.
        """
        directorio = os.path.dirname(path_str)
        ahora = time.monotonic()
        with self._lock:
            entrada = self._vcs_cache.get(directorio)
            if entrada and (ahora - entrada[0]) < VCS_CACHE_SECONDS:
                return os.path.basename(path_str) in entrada[1]

        try:
            proc = subprocess.run(
                ["git", "-C", directorio, "ls-files", "-z"],
                capture_output=True, timeout=GIT_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if proc.returncode != 0:  # no es un repo git
            versionados: set[str] = set()
        else:
            versionados = {
                nombre.split("/")[-1]
                for nombre in proc.stdout.decode("utf-8", "ignore").split("\0")
                if nombre and "/" not in nombre
            }

        with self._lock:
            self._vcs_cache[directorio] = (ahora, versionados)
        return os.path.basename(path_str) in versionados

    def _is_fresh(self, path_str: str) -> bool:
        try:
            return (time.time() - os.path.getmtime(path_str)) <= CREATION_MAX_AGE_SECONDS
        except OSError:
            return False

    def _handle(self, path_str: str, created: bool = False):
        language = self._should_track(path_str)
        if not language or self._debounced(path_str):
            return

        snap = self._read_snapshot(path_str)
        if snap is None:
            return

        with self._lock:
            old = self._cache.get(path_str)
            self._cache[path_str] = snap

        approx = snap.lines is None or (old is not None and old.lines is None)

        if old is None:
            # Un archivo desconocido solo cuenta como trabajo nuevo si acaba de
            # crearse. Si es preexistente (típico tras un restart del daemon),
            # se inicializa la caché en silencio para no inflar las métricas.
            if not (created and self._is_fresh(path_str)):
                return
            if self._es_versionado(path_str):
                return  # checkout/clone: el repo ya tenía este archivo
            self._emit(path_str, language, "write", snap.n_lines, 0, snap, approx)
            return

        if old.digest == snap.digest:
            return

        if approx:
            added = max(0, snap.n_lines - old.n_lines)
            deleted = max(0, old.n_lines - snap.n_lines)
        else:
            added, deleted = _real_diff(old.lines, snap.lines)
            if added == 0 and deleted == 0:
                return

        self._emit(path_str, language, "edit", added, deleted, snap, approx)

    def _emit(self, path_str, language, event_type, added, deleted, snap, approx):
        self._queue.put({
            "event_type": event_type,
            "timestamp": None,
            "file_path": path_str,
            "language": language,
            "details": {
                "lines_added": added,
                "lines_deleted": deleted,
                "lines": snap.n_lines,
                "diff": "line-count-only" if approx else "real",
                "source": "fs-watch",
            },
        })

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path, created=True)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path, created=True)


class FsWatcher:
    """Wrapper sobre watchdog.Observer + drenado async hacia la persistencia de devtrack."""

    def __init__(self, roots: list[Path], record_event: Callable[[dict], Awaitable[None]]):
        self._roots = [r for r in roots if r.is_dir()]
        self._record_event = record_event
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._observer: Observer | None = None
        self._consumer_task = None

    def start(self):
        import asyncio

        if not self._roots:
            logger.warning("fswatch: ningún root válido para vigilar — watcher no iniciado")
            return

        self._observer = Observer()
        handler = _Handler(self._queue)
        for root in self._roots:
            self._observer.schedule(handler, str(root), recursive=True)
        self._observer.start()
        logger.info(f"fswatch: vigilando {[str(r) for r in self._roots]}")

        self._consumer_task = asyncio.create_task(self._consume())

    async def _consume(self):
        import asyncio

        while True:
            item = await asyncio.to_thread(self._queue.get)
            try:
                await self._record_event(item)
            except Exception:
                logger.exception("fswatch: no se pudo persistir un evento")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("fswatch: detenido")
        if self._consumer_task:
            self._consumer_task.cancel()


def default_roots() -> list[Path]:
    env = os.environ.get("DEVTRACK_WATCH_ROOTS")
    if env:
        return [Path(p).expanduser() for p in env.split(",") if p.strip()]
    return [Path.home() / "projects"]
