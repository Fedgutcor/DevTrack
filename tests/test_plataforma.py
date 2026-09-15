"""Portabilidad: el CLI debe comportarse segun la plataforma real.

Estos tests nacen de un bug concreto: cli.py ramificaba `if win32 / else`,
asi que TODO lo que no era Windows -- incluido Linux -- caia en la rama de
macOS: logs en `~/Library/Logs` (que en Linux no existe) y arranque via
`launchctl` (que en Linux no existe).
"""
import importlib
import sys

import pytest


def _recargar_cli(monkeypatch, plataforma):
    monkeypatch.setattr(sys, "platform", plataforma)
    import devtrack.cli
    return importlib.reload(devtrack.cli)


@pytest.fixture(autouse=True)
def _restaurar():
    yield
    import devtrack.cli
    importlib.reload(devtrack.cli)


def test_linux_no_usa_library_logs(monkeypatch):
    """En Linux los logs NO van a ~/Library/Logs (es una ruta de macOS)."""
    cli = _recargar_cli(monkeypatch, "linux")
    assert "Library/Logs" not in str(cli.LOG_DIR), (
        f"LOG_DIR en Linux apunta a una ruta de macOS: {cli.LOG_DIR}"
    )


def test_linux_no_arranca_con_launchctl(monkeypatch):
    """En Linux no existe launchctl: el arranque no puede depender de el."""
    cli = _recargar_cli(monkeypatch, "linux")
    assert cli._modo_arranque() != "launchd", (
        "En Linux el CLI intenta arrancar con launchd/plist"
    )


def test_macos_sigue_usando_launchd(monkeypatch):
    """Control: en macOS el comportamiento actual no cambia."""
    cli = _recargar_cli(monkeypatch, "darwin")
    assert cli._modo_arranque() == "launchd"
    assert "Library/Logs" in str(cli.LOG_DIR)


def test_windows_usa_proceso_propio(monkeypatch):
    """Control: en Windows se arranca como proceso desacoplado."""
    cli = _recargar_cli(monkeypatch, "win32")
    assert cli._modo_arranque() == "proceso"


def test_windows_habilita_colores_ansi(monkeypatch):
    """Sin habilitar VT, la consola de Windows imprime los escapes en crudo.

    Se observa `_init_consola()`, que es donde vive la decision. Una version
    anterior de este test inyectaba el hook con raising=False y despues
    verificaba que existiera: se probaba a si misma.
    """
    import devtrack.cli as cli

    llamadas = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli, "_habilitar_ansi_windows", lambda: llamadas.append(1))
    assert cli._init_consola() is True
    assert llamadas, "En win32 no se habilitaron las secuencias ANSI"


def test_no_windows_no_toca_la_consola(monkeypatch):
    """Control negativo: fuera de Windows no se toca la consola."""
    import devtrack.cli as cli

    llamadas = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(cli, "_habilitar_ansi_windows", lambda: llamadas.append(1))
    assert cli._init_consola() is False
    assert not llamadas
