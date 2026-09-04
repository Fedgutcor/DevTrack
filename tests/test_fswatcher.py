"""Tests del watcher universal de filesystem.

Nivel: el _Handler contra archivos reales en disco. Es donde vive la decisión
de "esto se registra / esto se descarta", que es el comportamiento en disputa.
"""
import queue

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent

from devtrack.fswatcher import MAX_DIFF_BYTES, _Handler


@pytest.fixture
def handler():
    q: "queue.Queue[dict]" = queue.Queue()
    return _Handler(q), q


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _grande(path, n_lineas):
    """Escribe un archivo que supera MAX_DIFF_BYTES."""
    relleno = "x" * 500
    path.write_text("".join(f"<p>{relleno}-{i}</p>\n" for i in range(n_lineas)))
    assert path.stat().st_size > MAX_DIFF_BYTES, "el fixture debe superar el techo"


# --- Defecto 1: el techo de tamaño hace el archivo invisible para siempre ---

def test_archivo_grande_modificado_se_registra_aunque_no_se_pueda_diffear(handler, tmp_path):
    h, q = handler
    f = tmp_path / "lab.html"

    # Caché caliente: el archivo ya es conocido por el handler.
    _grande(f, 6000)
    h.on_modified(FileModifiedEvent(str(f)))
    _drain(q)

    # Cambio real de contenido en un archivo que supera el techo.
    h._last_seen.clear()  # saltar el debounce, no es lo que se prueba acá
    _grande(f, 6010)
    h.on_modified(FileModifiedEvent(str(f)))

    eventos = _drain(q)
    assert len(eventos) == 1, "un archivo >2MB que cambió debe producir un evento"
    ev = eventos[0]
    assert ev["language"] == "HTML"
    assert ev["details"]["lines"] == 6010
    assert ev["details"]["lines_added"] == 10
    assert ev["details"]["diff"] == "line-count-only"


def test_archivo_grande_sin_cambio_real_no_se_registra(handler, tmp_path):
    h, q = handler
    f = tmp_path / "lab.html"
    _grande(f, 6000)
    h.on_modified(FileModifiedEvent(str(f)))
    _drain(q)

    # Copia de deploy: mtime nuevo, contenido idéntico.
    h._last_seen.clear()
    _grande(f, 6000)
    h.on_modified(FileModifiedEvent(str(f)))

    assert _drain(q) == [], "contenido idéntico no debe registrarse"


# --- Defecto 2: la creación de un archivo nunca se registra ---

def test_creacion_de_archivo_se_registra_con_sus_lineas(handler, tmp_path):
    h, q = handler
    f = tmp_path / "nuevo.html"
    f.write_text("<p>uno</p>\n<p>dos</p>\n<p>tres</p>\n")

    h.on_created(FileCreatedEvent(str(f)))

    eventos = _drain(q)
    assert len(eventos) == 1, "crear un archivo debe registrarse"
    ev = eventos[0]
    assert ev["event_type"] == "write"
    assert ev["details"]["lines_added"] == 3
    assert ev["details"]["lines_deleted"] == 0
    assert ev["details"]["lines"] == 3


def test_creacion_de_archivo_grande_se_registra(handler, tmp_path):
    h, q = handler
    f = tmp_path / "nuevo-grande.html"
    _grande(f, 6000)

    h.on_created(FileCreatedEvent(str(f)))

    eventos = _drain(q)
    assert len(eventos) == 1
    assert eventos[0]["event_type"] == "write"
    assert eventos[0]["details"]["lines_added"] == 6000
    assert eventos[0]["details"]["diff"] == "line-count-only"


def test_archivo_preexistente_modificado_no_cuenta_como_lineas_nuevas(handler, tmp_path):
    """Un restart no debe inflar métricas: el primer on_modified de un archivo
    desconocido solo inicializa la caché."""
    h, q = handler
    f = tmp_path / "viejo.html"
    f.write_text("<p>a</p>\n" * 100)

    h.on_modified(FileModifiedEvent(str(f)))

    assert _drain(q) == [], "un archivo preexistente no es contenido nuevo"


# --- Integración: el evento del watcher tiene que llegar a loc_deltas ---

@pytest.mark.asyncio
async def test_evento_de_archivo_grande_llega_a_loc_deltas(tmp_path, monkeypatch):
    """El nivel que importa: un lab HTML de >2MB editado debe sumar LOC en el
    reporte, no solo aparecer en file_events."""
    import sqlite3 as _sqlite3
    from unittest.mock import patch

    import devtrack.db as db_module

    db_path = tmp_path / "t.sqlite3"
    with patch.object(db_module, "DB_PATH", db_path):
        import devtrack.main as main_module

        with patch.object(main_module.db, "DB_PATH", db_path):
            await db_module.init_db()
            main_module.state["session_id"] = await db_module.create_session("2026-09-03T10:00:00")

            q: "queue.Queue[dict]" = queue.Queue()
            h = _Handler(q)
            f = tmp_path / "lab.html"
            _grande(f, 6000)
            h.on_modified(FileModifiedEvent(str(f)))
            _drain(q)

            h._last_seen.clear()
            _grande(f, 6025)
            h.on_modified(FileModifiedEvent(str(f)))
            evento = _drain(q)[0]

            await main_module._record_event(evento)

    conn = _sqlite3.connect(str(db_path))
    filas = conn.execute(
        "SELECT lines_added, lines_deleted, language FROM loc_deltas"
    ).fetchall()
    conn.close()
    assert filas == [(25, 0, "HTML")]
