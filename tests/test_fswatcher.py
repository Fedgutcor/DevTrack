"""Tests del watcher universal de filesystem.

Nivel: el _Handler contra archivos reales en disco. Es donde vive la decisión
de "esto se registra / esto se descarta", que es el comportamiento en disputa.
"""
import queue
import sys

import pytest
from watchdog.events import FileCreatedEvent, FileDeletedEvent, FileModifiedEvent, FileMovedEvent

import devtrack.fswatcher as fswatcher
from devtrack.fswatcher import DEBOUNCE_SECONDS, MAX_DIFF_BYTES, _Handler


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

def test_archivo_grande_modificado_se_registra_aunque_no_se_pueda_diffear(handler, espacio_trabajo):
    h, q = handler
    f = espacio_trabajo / "lab.html"

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


def test_archivo_grande_sin_cambio_real_no_se_registra(handler, espacio_trabajo):
    h, q = handler
    f = espacio_trabajo / "lab.html"
    _grande(f, 6000)
    h.on_modified(FileModifiedEvent(str(f)))
    _drain(q)

    # Copia de deploy: mtime nuevo, contenido idéntico.
    h._last_seen.clear()
    _grande(f, 6000)
    h.on_modified(FileModifiedEvent(str(f)))

    assert _drain(q) == [], "contenido idéntico no debe registrarse"


# --- Defecto 2: la creación de un archivo nunca se registra ---

def test_creacion_de_archivo_se_registra_con_sus_lineas(handler, espacio_trabajo):
    h, q = handler
    f = espacio_trabajo / "nuevo.html"
    f.write_text("<p>uno</p>\n<p>dos</p>\n<p>tres</p>\n")

    h.on_created(FileCreatedEvent(str(f)))

    eventos = _drain(q)
    assert len(eventos) == 1, "crear un archivo debe registrarse"
    ev = eventos[0]
    assert ev["event_type"] == "write"
    assert ev["details"]["lines_added"] == 3
    assert ev["details"]["lines_deleted"] == 0
    assert ev["details"]["lines"] == 3


def test_creacion_de_archivo_grande_se_registra(handler, espacio_trabajo):
    h, q = handler
    f = espacio_trabajo / "nuevo-grande.html"
    _grande(f, 6000)

    h.on_created(FileCreatedEvent(str(f)))

    eventos = _drain(q)
    assert len(eventos) == 1
    assert eventos[0]["event_type"] == "write"
    assert eventos[0]["details"]["lines_added"] == 6000
    assert eventos[0]["details"]["diff"] == "line-count-only"


def test_archivo_preexistente_modificado_no_cuenta_como_lineas_nuevas(handler, espacio_trabajo):
    """Un restart no debe inflar métricas: el primer on_modified de un archivo
    desconocido solo inicializa la caché."""
    h, q = handler
    f = espacio_trabajo / "viejo.html"
    f.write_text("<p>a</p>\n" * 100)

    h.on_modified(FileModifiedEvent(str(f)))

    assert _drain(q) == [], "un archivo preexistente no es contenido nuevo"


# --- Integración: el evento del watcher tiene que llegar a loc_deltas ---

@pytest.mark.asyncio
async def test_evento_de_archivo_grande_llega_a_loc_deltas(espacio_trabajo, monkeypatch):
    """El nivel que importa: un lab HTML de >2MB editado debe sumar LOC en el
    reporte, no solo aparecer en file_events."""
    import sqlite3 as _sqlite3
    from unittest.mock import patch

    import devtrack.db as db_module

    db_path = espacio_trabajo / "t.sqlite3"
    with patch.object(db_module, "DB_PATH", db_path):
        import devtrack.main as main_module

        with patch.object(main_module.db, "DB_PATH", db_path):
            await db_module.init_db()
            main_module.state["session_id"] = await db_module.create_session("2026-09-03T10:00:00")

            q: "queue.Queue[dict]" = queue.Queue()
            h = _Handler(q)
            f = espacio_trabajo / "lab.html"
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


# --- Una creación por checkout/clone no es trabajo ---

def _repo(espacio_trabajo):
    import subprocess
    subprocess.run(["git", "init", "-q", str(espacio_trabajo)], check=True)
    subprocess.run(["git", "-C", str(espacio_trabajo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(espacio_trabajo), "config", "user.name", "t"], check=True)
    return espacio_trabajo


def test_creacion_de_archivo_ya_versionado_no_cuenta_como_trabajo(handler, espacio_trabajo):
    """`git worktree add` / `clone` / `checkout` materializan archivos que ya
    están en el repo. Contarlos metió un worktree entero al reporte:
    +80.059 LOC en 1.289 archivos que ya estaban versionados."""
    import subprocess

    h, q = handler
    repo = _repo(espacio_trabajo)
    f = repo / "ya-existente.html"
    f.write_text("<p>del repo</p>\n" * 50)
    subprocess.run(["git", "-C", str(repo), "add", "ya-existente.html"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)

    h.on_created(FileCreatedEvent(str(f)))

    assert _drain(q) == [], "un archivo versionado que aparece no es trabajo nuevo"


def test_creacion_de_archivo_sin_versionar_si_cuenta(handler, espacio_trabajo):
    h, q = handler
    repo = _repo(espacio_trabajo)
    f = repo / "recien-escrito.html"
    f.write_text("<p>a</p>\n<p>b</p>\n")

    h.on_created(FileCreatedEvent(str(f)))

    eventos = _drain(q)
    assert len(eventos) == 1, "un archivo nuevo sin versionar es trabajo real"
    assert eventos[0]["details"]["lines_added"] == 2


def test_creacion_fuera_de_un_repo_git_si_cuenta(handler, espacio_trabajo):
    """Sin repo no hay checkout posible: un archivo suelto es trabajo."""
    h, q = handler
    f = espacio_trabajo / "suelto.html"
    f.write_text("<p>a</p>\n")

    h.on_created(FileCreatedEvent(str(f)))

    assert len(_drain(q)) == 1


# --- Bajo ráfaga continua el debounce no debe callarse para siempre ---

@pytest.fixture
def reloj(monkeypatch):
    """Reloj controlado: el debounce se prueba con tiempo simulado."""
    # El parche es de módulo: _es_versionado también lee monotonic para el TTL
    # de su caché. No afecta a estos tests (van por on_modified, que nunca lo
    # llama), pero un test de ráfaga con on_created tendría que acotarlo.
    estado = {"t": 1000.0}
    monkeypatch.setattr("devtrack.fswatcher.time.monotonic", lambda: estado["t"])
    return estado


def test_rafaga_continua_no_silencia_el_archivo_para_siempre(handler, espacio_trabajo, reloj):
    """Un editor que emite un evento por segundo reseteaba el reloj en cada uno.

    El archivo cambiaba de verdad en cada paso y solo se registraba el primero:
    no era un debounce, era un throttle que no volvía a disparar.
    """
    h, q = handler
    f = espacio_trabajo / "en-rafaga.html"
    f.write_text("<p>0</p>\n")
    h.on_modified(FileModifiedEvent(str(f)))  # inicializa la caché
    _drain(q)

    for i in range(1, 11):           # 10 segundos de ráfaga, 1 evento/s
        reloj["t"] += 1.0
        f.write_text("<p>x</p>\n" * i)
        h.on_modified(FileModifiedEvent(str(f)))

    eventos = _drain(q)
    assert len(eventos) >= 4, (
        f"10s de cambios reales con ventana de {DEBOUNCE_SECONDS}s deben producir "
        f"al menos 4 registros; se produjeron {len(eventos)}"
    )


def test_la_ventana_sigue_absorbiendo_las_rafagas_de_autosave(handler, espacio_trabajo, reloj):
    """Control: varios eventos dentro de la misma ventana siguen colapsando."""
    h, q = handler
    f = espacio_trabajo / "autosave.html"
    f.write_text("<p>0</p>\n")
    h.on_modified(FileModifiedEvent(str(f)))
    _drain(q)

    for i in range(1, 6):            # 5 eventos en 0.5s
        reloj["t"] += 0.1
        f.write_text("<p>x</p>\n" * i)
        h.on_modified(FileModifiedEvent(str(f)))

    assert len(_drain(q)) <= 1, "una ráfaga dentro de la ventana no se registra 5 veces"


# --- Defecto: la caché de snapshots crecía sin tope y nunca se vaciaba ---
#
# Cada archivo visto dejaba en `_cache` TODAS sus líneas, y nada las sacaba:
# ni un tope ni el borrado del archivo. Un checkout de miles de archivos las
# metía todas de golpe. Medido en un daemon con 9 días encendido: 13 GB de
# memoria, casi todo en swap.


def _bytes_en_cache(h) -> int:
    """Memoria real de las líneas guardadas, medida desde afuera."""
    return sum(
        sys.getsizeof(s.lines) + sum(sys.getsizeof(linea) for linea in s.lines)
        for s in h._cache.values() if s.lines
    )


def test_la_cache_respeta_su_tope_aunque_pasen_miles_de_archivos(handler, espacio_trabajo, monkeypatch):
    h, _q = handler
    monkeypatch.setattr(fswatcher, "MAX_CACHE_BYTES", 200_000)
    rutas = []
    for i in range(300):
        p = espacio_trabajo / f"m{i}.py"
        p.write_text("".join(f"linea_{i}_{j} = {j}\n" for j in range(40)))
        h.on_modified(FileModifiedEvent(str(p)))
        rutas.append(str(p))

    assert len(h._cache) < 300, "la caché guardó los 300 archivos: no tiene tope"
    assert _bytes_en_cache(h) <= 200_000
    assert rutas[-1] in h._cache, "lo último visto debe seguir en caché (LRU)"


def test_borrar_un_archivo_lo_saca_de_la_cache(handler, espacio_trabajo):
    h, _q = handler
    p = espacio_trabajo / "borrable.py"
    p.write_text("a = 1\n")
    h.on_modified(FileModifiedEvent(str(p)))
    assert str(p) in h._cache, "precondición: el archivo entró a la caché"

    p.unlink()
    h.on_deleted(FileDeletedEvent(str(p)))

    assert str(p) not in h._cache


def test_mover_un_archivo_saca_la_ruta_vieja_de_la_cache(handler, espacio_trabajo):
    h, _q = handler
    viejo, nuevo = espacio_trabajo / "viejo.py", espacio_trabajo / "nuevo.py"
    viejo.write_text("a = 1\n")
    h.on_modified(FileModifiedEvent(str(viejo)))
    assert str(viejo) in h._cache, "precondición: el archivo entró a la caché"

    viejo.rename(nuevo)
    h.on_moved(FileMovedEvent(str(viejo), str(nuevo)))

    assert str(viejo) not in h._cache


def test_las_marcas_de_debounce_vencidas_no_se_acumulan(handler, reloj, monkeypatch):
    # Una marca más vieja que DEBOUNCE_SECONDS vale lo mismo que no tenerla.
    h, _q = handler
    monkeypatch.setattr(fswatcher, "MAX_MARCAS", 50)
    for i in range(500):
        h._registrado(f"/x/f{i}.py")
        reloj["t"] += DEBOUNCE_SECONDS + 1

    assert len(h._last_seen) <= 50 + 1


def test_la_cache_de_versionados_no_guarda_entradas_vencidas(handler, reloj, monkeypatch, tmp_path):
    # Una entrada más vieja que VCS_CACHE_SECONDS nunca se vuelve a usar.
    h, _q = handler
    monkeypatch.setattr(fswatcher, "MAX_MARCAS", 50)

    class _Proc:
        returncode = 0
        stdout = b"a.py\0"

    monkeypatch.setattr(fswatcher.subprocess, "run", lambda *a, **k: _Proc())
    for i in range(500):
        h._es_versionado(str(tmp_path / f"d{i}" / "a.py"))
        reloj["t"] += fswatcher.VCS_CACHE_SECONDS + 1

    assert len(h._vcs_cache) <= 50 + 1

# --- Clasificación de artefactos generados (2026-09-18) -------------------
#
# Origen: el dashboard reportó 1.295.712 "líneas escritas" en un día, de las
# cuales 1.190.572 venían de UN evento sobre `graphify-out/graph.json`: la
# salida de un generador, no trabajo humano. `TELEMETRY_DIRS` ya contenía
# "out", pero la comparación es por igualdad de componente y `graphify-out`
# no es `out`, así que el archivo se clasificó como JSON y entró a la métrica
# de titular.
#
# Se clasifica, no se descarta: descartar volvería el archivo invisible para
# siempre, que es la decisión que `MAX_DIFF_BYTES` ya documenta en contra.

GRAPH_OUT = (
    "/home/usuario/projects/mi-app-wt/una-rama"
    "/graphify-out/graph.json"
)


def _tracker() -> _Handler:
    return _Handler(queue.Queue())


def test_directorio_con_sufijo_out_es_telemetria():
    """`graphify-out/` es salida de un generador, como `out/`."""
    assert _tracker()._should_track(GRAPH_OUT) == "Telemetry"


def test_sufijo_out_con_guion_bajo_tambien():
    ruta = "/home/usuario/projects/proj/render_out/data.json"
    assert _tracker()._should_track(ruta) == "Telemetry"


def test_los_temporales_del_canario_no_cuentan_como_proyecto():
    """El detector no debe contaminar la métrica que él mismo vigila.

    Se clasifican como telemetría y NO se ignoran: el canario verifica su
    propia cobertura consultando `file_events` sin filtrar por `language`,
    así que ignorarlos lo dejaría ciego (reportaría "no registró" en las
    tres raíces, para siempre).
    """
    ruta = "/home/usuario/projects/.devtrack-canario-1789711746009.md"
    assert _tracker()._should_track(ruta) == "Telemetry"


def test_un_out_que_es_parte_de_una_palabra_no_es_telemetria():
    """Control negativo: `layout/`, `checkout/` y `routes/` NO son salidas."""
    for d in ("layout", "checkout", "routes", "about"):
        ruta = f"/home/usuario/projects/app/{d}/index.ts"
        assert _tracker()._should_track(ruta) == "TypeScript", d


def test_el_codigo_fuente_normal_sigue_contando():
    """Control positivo: sin él, un `_should_track` que devuelva siempre
    'Telemetry' pasaría los tres tests de arriba."""
    ruta = "/home/usuario/projects/devtrack/devtrack/main.py"
    assert _tracker()._should_track(ruta) == "Python"
