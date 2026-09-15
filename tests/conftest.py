"""Fixtures compartidos.

`espacio_trabajo` reemplaza a `tmp_path` en los tests del watcher.

Por que: `IGNORED_DIRS` incluye "tmp" y `_is_ignored()` compara **por segmento
de ruta**, asi que cualquier archivo bajo `/tmp/...` se descarta — que es el
comportamiento correcto del producto. Pero el `tmp_path` de pytest vive en
`/tmp/pytest-of-<user>/...` en Linux y en `/private/var/folders/...` en macOS:
los mismos tests pasaban en una plataforma y fallaban en la otra, y el CI
llevaba en rojo desde el 2026-09-04 por esto. El defecto estaba en el arnes,
no en el watcher.
"""
import shutil
import tempfile
from pathlib import Path

import pytest

from devtrack.fswatcher import _is_ignored


@pytest.fixture
def espacio_trabajo(tmp_path_factory):
    """Directorio temporal sin segmentos que el watcher ignore."""
    base = Path(__file__).resolve().parent.parent / ".espacio-tests"
    base.mkdir(exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="ws-", dir=base))
    assert not _is_ignored(d / "x.py"), (
        f"el propio espacio de trabajo cae en IGNORED_DIRS: {d}"
    )
    yield d
    shutil.rmtree(d, ignore_errors=True)
