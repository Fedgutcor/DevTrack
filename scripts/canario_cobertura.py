#!/usr/bin/env python3
"""Canario de cobertura: ¿devtrack REGISTRA lo que dice vigilar?

Un test unitario de `declared_roots()` prueba que la config se lee. No prueba
que el watcher escriba un evento cuando el usuario guarda un archivo — que es
lo único que le importa al director. Este canario cierra esa brecha: escribe
un archivo real en cada raíz declarada, espera el debounce y verifica que el
evento haya llegado a la base.

Nació del defecto del 2026-09-05: el watcher llevaba semanas vigilando sólo
`~/projects` mientras el trabajo real (actas de cliente, propuestas, clases)
se escribía fuera y quedaba invisible. Nadie se enteró porque nada medía la
cobertura REAL — sólo se asumía.

TRI-ESTADO A PROPÓSITO (F7). Un canario que no puede medir NO dice "todo mal"
ni "todo bien": dice INCONCLUSO. Si el watcher está muerto o la base no existe,
un veredicto rojo mandaría a arreglar la raíz equivocada y un verde sería una
mentira. Los tres códigos de salida:

    0  OK          todas las raíces declaradas registran
    1  FALLO       alguna raíz declarada NO registró (cobertura rota)
    2  INCONCLUSO  no se pudo medir (watcher caído, base ausente)

CONTROL POSITIVO OBLIGATORIO. Antes de creerle a un cero, el canario verifica
que el watcher esté vivo y escribiendo. Sin eso, "ningún evento" es ambiguo:
el 2026-09-05 una sonda dio 0/4 y parecía exonerar a la hipótesis del acento
cuando en realidad el watcher ni miraba ese directorio.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devtrack.fswatcher import declared_roots  # noqa: E402

DB = Path.home() / ".local" / "share" / "devtrack" / "devtrack.sqlite3"
PREFIJO = ".devtrack-canario-"

OK, FALLO, INCONCLUSO = 0, 1, 2


def _conectar() -> sqlite3.Connection | None:
    if not DB.exists():
        return None
    try:
        return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _watcher_vivo(conn: sqlite3.Connection, ventana_min: int = 120) -> tuple[bool, str]:
    """Control positivo: ¿la base recibió algún evento reciente?

    No se usa `pgrep`: un proceso vivo que no escribe es indistinguible de uno
    muerto para lo que acá importa. La señal es la ESCRITURA, no el PID.
    """
    desde = (datetime.now() - timedelta(minutes=ventana_min)).isoformat()
    try:
        n = conn.execute(
            "SELECT count(*) FROM file_events WHERE timestamp >= ?", (desde,)
        ).fetchone()[0]
    except sqlite3.Error as exc:
        return False, f"no se pudo consultar file_events: {exc}"
    if n == 0:
        return False, (
            f"cero eventos en los últimos {ventana_min} min — el watcher no está "
            "escribiendo, así que un 'no registró' no probaría nada"
        )
    return True, f"{n} eventos recientes"


def _sondear(conn: sqlite3.Connection, raiz: Path, espera: float) -> tuple[bool, str]:
    """Escribe un archivo real en `raiz` y verifica que aparezca en la base."""
    if not raiz.is_dir():
        return False, "la raíz DECLARADA no existe en el disco"

    marca = f"{PREFIJO}{int(time.time() * 1000)}.md"
    sonda = raiz / marca
    try:
        sonda.write_text(
            f"# canario de cobertura devtrack\n\n{datetime.now().isoformat()}\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"no se pudo escribir la sonda: {exc}"

    try:
        time.sleep(espera)
        n = conn.execute(
            "SELECT count(*) FROM file_events WHERE file_path LIKE ?", (f"%{marca}%",)
        ).fetchone()[0]
        return (n > 0), ("registrado" if n else "NO registrado tras la espera")
    except sqlite3.Error as exc:
        return False, f"no se pudo consultar: {exc}"
    finally:
        sonda.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--espera",
        type=float,
        default=float(os.environ.get("CANARIO_ESPERA", "45")),
        help="segundos a esperar el debounce del watcher (default 45)",
    )
    args = ap.parse_args()

    conn = _conectar()
    if conn is None:
        print(f"INCONCLUSO: la base de devtrack no existe o no se puede abrir ({DB})")
        return INCONCLUSO

    vivo, detalle = _watcher_vivo(conn)
    if not vivo:
        print(f"INCONCLUSO: {detalle}")
        return INCONCLUSO
    print(f"control positivo OK — {detalle}\n")

    raices = declared_roots()
    if not raices:
        print("INCONCLUSO: ninguna raíz declarada")
        return INCONCLUSO

    fallos: list[str] = []
    for raiz in raices:
        ok, detalle = _sondear(conn, raiz, args.espera)
        print(f"  [{'OK ' if ok else 'FALLO'}] {raiz} — {detalle}")
        if not ok:
            fallos.append(f"{raiz}: {detalle}")

    print()
    if fallos:
        print(f"FALLO: {len(fallos)} de {len(raices)} raíces declaradas no registran.")
        for f in fallos:
            print(f"  · {f}")
        return FALLO

    print(f"OK: las {len(raices)} raíces declaradas registran eventos.")
    return OK


if __name__ == "__main__":
    sys.exit(main())
