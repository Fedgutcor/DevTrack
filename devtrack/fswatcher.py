"""Universal filesystem watcher — captura ediciones de cualquier editor/IDE
(Antigravity, Vim, JetBrains, terminal, etc.), no solo Claude Code.

Corre un watchdog.Observer en un hilo de SO y empuja eventos ya normalizados
a una cola thread-safe que un task async drena hacia la misma ruta de
persistencia que usa POST /events.
"""
import difflib
import logging
import os
import queue
import threading
import time
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

EXT_MAP = {
    '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript',
    '.js': 'JavaScript', '.jsx': 'JavaScript', '.go': 'Go',
    '.rs': 'Rust', '.sh': 'Shell', '.md': 'Markdown',
    '.css': 'CSS', '.scss': 'SCSS', '.html': 'HTML',
    '.json': 'JSON', '.toml': 'TOML', '.yml': 'YAML', '.yaml': 'YAML',
    '.sql': 'SQL', '.swift': 'Swift', '.kt': 'Kotlin', '.rb': 'Ruby',
}

DEBOUNCE_SECONDS = 2.0
MAX_DIFF_BYTES = 2_000_000  # no leer/diffear archivos gigantes (binarios mal detectados, dumps, etc.)


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS or part.endswith(".egg-info") for part in path.parts)


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
        self._cache: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def _should_track(self, path_str: str) -> str | None:
        p = Path(path_str)
        if _is_ignored(p):
            return None
        ext = p.suffix.lower()
        return EXT_MAP.get(ext)

    def _debounced(self, path_str: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last_seen.get(path_str, 0.0)
            self._last_seen[path_str] = now
        return (now - last) < DEBOUNCE_SECONDS

    def _read_lines(self, path_str: str) -> list[str] | None:
        try:
            if os.path.getsize(path_str) > MAX_DIFF_BYTES:
                return None
            with open(path_str, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().splitlines()
        except OSError:
            return None

    def _handle(self, path_str: str):
        language = self._should_track(path_str)
        if not language or self._debounced(path_str):
            return

        new_lines = self._read_lines(path_str)
        if new_lines is None:
            return

        with self._lock:
            old_lines = self._cache.get(path_str)
            self._cache[path_str] = new_lines

        if old_lines is None:
            event_type = "write"
            lines_added, lines_deleted = len(new_lines), 0
        else:
            if old_lines == new_lines:
                return
            event_type = "edit"
            lines_added, lines_deleted = _real_diff(old_lines, new_lines)

        self._queue.put({
            "event_type": event_type,
            "timestamp": None,
            "file_path": path_str,
            "language": language,
            "details": {
                "lines_added": lines_added,
                "lines_deleted": lines_deleted,
                "lines": len(new_lines),
                "source": "fs-watch",
            },
        })

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


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
