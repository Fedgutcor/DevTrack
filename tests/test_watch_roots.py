"""Cobertura de raíces vigiladas — el defecto que volvió invisible el trabajo real.

CONTEXTO (medido 2026-09-05). `default_roots()` devolvía `[~/projects]` y la
variable `DEVTRACK_WATCH_ROOTS` no estaba seteada en el proceso, así que todo
lo escrito fuera de esa raíz no lo veía el fswatcher: 177 deltas / 11.561
líneas en una semana, incluyendo actas de cliente
(`~/actas-dconcept-2026-09/`), propuestas (`~/Documents/propuestas-clientes/`),
la convocatoria del ITM y los HTML de clase.

Es F4 de la doctrina de flota ("ningún proyecto fuera del radar") con un
agravante: F4 declara `~/projects` **y `~/apps`**, y el default ni siquiera
incluía la segunda.

DECISIÓN DEL DIRECTOR (2026-09-05): raíces declaradas explícitamente, en un
archivo de config — no `$HOME` entero con exclusiones.
"""

from pathlib import Path

import pytest

from devtrack.fswatcher import FsWatcher, declared_roots, default_roots


@pytest.fixture(autouse=True)
def _sin_env(monkeypatch):
    """Cada test declara su propio entorno: sin herencia del proceso real."""
    monkeypatch.delenv("DEVTRACK_WATCH_ROOTS", raising=False)


class TestRaicesPorDefecto:
    def test_incluye_projects_y_apps(self, monkeypatch, tmp_path):
        """F4 declara DOS raíces. El default sólo traía una."""
        monkeypatch.setenv("HOME", str(tmp_path))
        roots = declared_roots(config_path=tmp_path / "no-existe")
        nombres = {r.name for r in roots}
        assert "projects" in nombres
        assert "apps" in nombres, "F4 declara ~/apps y el default lo omitía"


class TestRaicesDeclaradas:
    def test_lee_las_raices_del_archivo_de_config(self, tmp_path):
        cfg = tmp_path / "roots.txt"
        cfg.write_text(
            f"{tmp_path}/actas\n{tmp_path}/Documents/propuestas\n",
            encoding="utf-8",
        )
        roots = declared_roots(config_path=cfg)
        assert tmp_path / "actas" in roots
        assert tmp_path / "Documents/propuestas" in roots

    def test_ignora_comentarios_y_lineas_vacias(self, tmp_path):
        cfg = tmp_path / "roots.txt"
        cfg.write_text(
            f"# raíces de trabajo comercial\n\n{tmp_path}/actas\n   \n",
            encoding="utf-8",
        )
        assert declared_roots(config_path=cfg) == [tmp_path / "actas"]

    def test_expande_el_tilde(self, tmp_path, monkeypatch):
        # `Path.expanduser()` resuelve por la env var HOME, no por `Path.home()`:
        # parchear el classmethod deja el test verde contra el home REAL.
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = tmp_path / "roots.txt"
        cfg.write_text("~/actas-dconcept-2026-09\n", encoding="utf-8")
        assert declared_roots(config_path=cfg) == [tmp_path / "actas-dconcept-2026-09"]

    def test_la_env_var_gana_sobre_el_archivo(self, tmp_path, monkeypatch):
        cfg = tmp_path / "roots.txt"
        cfg.write_text(f"{tmp_path}/del-archivo\n", encoding="utf-8")
        monkeypatch.setenv("DEVTRACK_WATCH_ROOTS", f"{tmp_path}/de-la-env")
        assert declared_roots(config_path=cfg) == [tmp_path / "de-la-env"]

    def test_no_duplica_una_raiz_repetida(self, tmp_path):
        cfg = tmp_path / "roots.txt"
        cfg.write_text(f"{tmp_path}/a\n{tmp_path}/a\n", encoding="utf-8")
        assert declared_roots(config_path=cfg) == [tmp_path / "a"]


class TestRaizDeclaradaQueNoExiste:
    """F7 dentro del watcher: declarado != vigilado.

    `FsWatcher.__init__` hacía `[r for r in roots if r.is_dir()]`, así que una
    raíz con un typo desaparecía SIN AVISO y el watcher arrancaba feliz
    vigilando menos de lo que el usuario creía. Un universo más chico
    reportando verde — exactamente lo que la doctrina prohíbe.
    """

    def test_expone_las_raices_faltantes_en_vez_de_tragarlas(self, tmp_path):
        existe = tmp_path / "existe"
        existe.mkdir()
        falta = tmp_path / "typo-en-la-ruta"

        w = FsWatcher([existe, falta], record_event=None)

        assert w.roots == [existe]
        assert w.missing_roots == [falta], (
            "una raíz declarada que no existe debe quedar VISIBLE, no descartada"
        )

    def test_sin_faltantes_la_lista_queda_vacia(self, tmp_path):
        existe = tmp_path / "existe"
        existe.mkdir()
        assert FsWatcher([existe], record_event=None).missing_roots == []


class TestCompatibilidad:
    def test_default_roots_sigue_devolviendo_paths(self, tmp_path, monkeypatch):
        """No romper al consumidor existente (`main.py` la llama sin argumentos)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        roots = default_roots()
        assert isinstance(roots, list)
        assert all(isinstance(r, Path) for r in roots)
