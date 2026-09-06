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
import sys
import threading
import time
from collections import OrderedDict
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
#: Tope de memoria de la caché de snapshots: las líneas de la última versión
#: vista de cada archivo, que hacen falta para el diff real. Sin tope crecía con
#: cada archivo visto y no se vaciaba nunca; un checkout de miles de archivos
#: las metía todas de golpe (medido: 13 GB en un daemon con 9 días encendido).
#: Al pasarse se descarta lo usado hace más tiempo: ese archivo, si vuelve a
#: cambiar, se trata como recién visto (se re-cachea sin sumar líneas).
MAX_CACHE_BYTES = 64 * 1024 * 1024
#: Pasado este número de entradas, las marcas de debounce y la caché de
#: versionados se podan de lo vencido (una entrada vencida vale lo mismo que
#: no tenerla). Sin poda crecían con cada archivo y directorio visto.
MAX_MARCAS = 4096


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
        # LRU acotada por MAX_CACHE_BYTES; ver `_cachear`.
        self._cache: "OrderedDict[str, _Snapshot]" = OrderedDict()
        self._cache_bytes = 0
        self._vcs_cache: dict[str, tuple[float, set[str]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _peso(snap: _Snapshot) -> int:
        """Memoria que ocupan las líneas guardadas (lo único que pesa)."""
        if not snap.lines:
            return 0
        return sys.getsizeof(snap.lines) + sum(sys.getsizeof(linea) for linea in snap.lines)

    def _cachear(self, path_str: str, snap: _Snapshot) -> _Snapshot | None:
        """Guarda el snapshot y devuelve el anterior. Llamar con `_lock` tomado.

        Al pasarse de MAX_CACHE_BYTES descarta lo usado hace más tiempo; nunca
        el que se acaba de guardar."""
        old = self._cache.pop(path_str, None)
        if old is not None:
            self._cache_bytes -= self._peso(old)
        self._cache[path_str] = snap
        self._cache_bytes += self._peso(snap)
        while self._cache_bytes > MAX_CACHE_BYTES and len(self._cache) > 1:
            _, fuera = self._cache.popitem(last=False)
            self._cache_bytes -= self._peso(fuera)
        return old

    def _olvidar(self, path_str: str) -> None:
        """El archivo ya no existe en esa ruta: nada que comparar después."""
        with self._lock:
            old = self._cache.pop(path_str, None)
            if old is not None:
                self._cache_bytes -= self._peso(old)
            self._last_seen.pop(path_str, None)

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
        """¿Este evento cae dentro de la ventana del último REGISTRADO?

        El reloj se marca en `_registrado()`, no acá: antes se escribía en cada
        llamada, incluidas las que terminaban descartadas, así que una ráfaga
        continua de eventos separados por menos de DEBOUNCE_SECONDS lo reseteaba
        indefinidamente y el archivo no se registraba NUNCA. Medido con 10s de
        cambios reales a 1 evento/s: cero registros.

        Con la marca movida al momento del registro, una ráfaga produce un
        evento por ventana. El último cambio de una ráfaga que después no se
        vuelve a tocar queda sin registrar hasta el próximo evento del archivo;
        no se pierde el diff, porque la caché guarda el último snapshot EMITIDO
        y el evento siguiente recupera el delta completo.
        """
        with self._lock:
            last = self._last_seen.get(path_str, 0.0)
        return (time.monotonic() - last) < DEBOUNCE_SECONDS

    def _registrado(self, path_str: str) -> None:
        ahora = time.monotonic()
        with self._lock:
            self._last_seen[path_str] = ahora
            if len(self._last_seen) > MAX_MARCAS:
                self._last_seen = {
                    p: t for p, t in self._last_seen.items() if ahora - t < DEBOUNCE_SECONDS
                }

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
        Contarlos metió un worktree entero al reporte como trabajo nuevo:
        +80.059 LOC en 1.289 archivos que ya estaban versionados.

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
            if len(self._vcs_cache) > MAX_MARCAS:
                self._vcs_cache = {
                    d: e for d, e in self._vcs_cache.items() if ahora - e[0] < VCS_CACHE_SECONDS
                }
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
            old = self._cachear(path_str, snap)

        approx =snap.lines is None or (old is not None and old.lines is None)

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
        self._registrado(path_str)
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
            self._olvidar(event.src_path)
            self._handle(event.dest_path, created=True)

    def on_deleted(self, event):
        if not event.is_directory:
            self._olvidar(event.src_path)


class FsWatcher:
    """Wrapper sobre watchdog.Observer + drenado async hacia la persistencia de devtrack."""

    def __init__(self, roots: list[Path], record_event: Callable[[dict], Awaitable[None]]):
        # Las raíces declaradas que NO existen se separan en vez de descartarse
        # en silencio. Antes esto era `[r for r in roots if r.is_dir()]`: un typo
        # en una ruta desaparecía sin aviso y el watcher arrancaba "OK" vigilando
        # un universo más chico del que el usuario creía — declarado != vigilado.
        self._roots = [r for r in roots if r.is_dir()]
        self.missing_roots = [r for r in roots if not r.is_dir()]
        self._record_event = record_event
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._observer: Observer | None = None
        self._consumer_task = None

    @property
    def roots(self) -> list[Path]:
        """Raíces que se están vigilando de verdad (simétrico con `missing_roots`)."""
        return list(self._roots)

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
        if self.missing_roots:
            logger.warning(
                "fswatch: %d raíz/raíces DECLARADAS que no existen y NO se están "
                "vigilando: %s — revisá el archivo de raíces o creá el directorio.",
                len(self.missing_roots),
                [str(r) for r in self.missing_roots],
            )

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


# Archivo donde el usuario DECLARA qué raíces se vigilan. Se eligió un archivo
# (y no sólo una env var) porque la env var no sobrevive a un reinicio del
# proceso ni queda a la vista: el 2026-09-05 se midió que `DEVTRACK_WATCH_ROOTS`
# no estaba seteada y nadie lo sabía, así que el watcher llevaba semanas
# vigilando una sola raíz mientras el trabajo real (actas de cliente,
# propuestas, clases) se escribía fuera de ella y quedaba invisible.
ROOTS_CONFIG_PATH = Path.home() / ".config" / "devtrack" / "roots.txt"

# F4 de la doctrina de flota declara DOS raíces por defecto, no una. El default
# anterior era sólo `~/projects` y por eso `~/apps` nunca se vigiló.
_FALLBACK_ROOTS = ("projects", "apps")


def _parse_roots(lineas) -> list[Path]:
    """Una ruta por línea; `#` comienza un comentario; se expande `~`.

    Devuelve las rutas SIN filtrar por existencia: quién decide qué hacer con
    una raíz declarada que falta es `FsWatcher`, que la reporta.
    """
    vistos: list[Path] = []
    for linea in lineas:
        texto = linea.split("#", 1)[0].strip()
        if not texto:
            continue
        ruta = Path(texto).expanduser()
        if ruta not in vistos:
            vistos.append(ruta)
    return vistos


def declared_roots(config_path: Path | None = None) -> list[Path]:
    """Raíces a vigilar, por precedencia: env var > archivo de config > default.

    `config_path` existe para los tests; en producción se usa
    `ROOTS_CONFIG_PATH`.
    """
    env = os.environ.get("DEVTRACK_WATCH_ROOTS")
    if env:
        return _parse_roots(env.split(","))

    cfg = ROOTS_CONFIG_PATH if config_path is None else config_path
    try:
        if cfg.is_file():
            declaradas = _parse_roots(cfg.read_text(encoding="utf-8").splitlines())
            if declaradas:
                return declaradas
    except OSError:
        # Un archivo de config ilegible no puede dejar al watcher sin raíces:
        # se cae al default y el arranque lo registra.
        logger.warning("fswatch: no se pudo leer %s — usando raíces por defecto", cfg)

    return [Path.home() / nombre for nombre in _FALLBACK_ROOTS]


def default_roots() -> list[Path]:
    """Compat: `main.py` la llama sin argumentos."""
    return declared_roots()
