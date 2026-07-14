import socket
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import devtrack.db as db_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient con DB temporal y FsWatcher deshabilitado (root inexistente)."""
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("DEVTRACK_WATCH_ROOTS", str(tmp_path / "no-such-dir"))
    with patch.object(db_module, "DB_PATH", db_path):
        import devtrack.main as main_module

        with patch.object(main_module.db, "DB_PATH", db_path):
            with TestClient(main_module.app) as c:
                yield c, db_path


def _fetchall(db_path, query, params=()):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return rows


def test_session_created_on_startup_records_current_hostname(client):
    _, db_path = client
    rows = _fetchall(db_path, "SELECT host FROM sessions")
    assert len(rows) >= 1
    assert rows[0]["host"] == socket.gethostname()


def test_post_edit_event_records_host_in_loc_deltas(client):
    c, db_path = client
    resp = c.post(
        "/events",
        json={
            "event_type": "edit",
            "file_path": "/tmp/projects/foo/bar.py",
            "details": {"lines_added": 5, "lines_deleted": 1},
        },
    )
    assert resp.status_code == 200

    rows = _fetchall(db_path, "SELECT host, lines_added, lines_deleted FROM loc_deltas")
    assert len(rows) == 1
    assert rows[0]["host"] == socket.gethostname()
    assert rows[0]["lines_added"] == 5


def test_post_edit_event_records_host_in_file_events(client):
    c, db_path = client
    resp = c.post(
        "/events",
        json={
            "event_type": "edit",
            "file_path": "/tmp/projects/foo/bar.py",
            "details": {"lines_added": 5, "lines_deleted": 1},
        },
    )
    assert resp.status_code == 200

    rows = _fetchall(db_path, "SELECT host FROM file_events")
    assert len(rows) == 1
    assert rows[0]["host"] == socket.gethostname()


def test_detect_project():
    from devtrack.main import detect_project
    
    # Path UNIX con 'projects' en minúsculas
    assert detect_project("/Users/foo/projects/mi-proyecto/src/main.py") == "mi-proyecto"
    
    # Path Windows con 'Projects' en mayúsculas
    assert detect_project("C:\\Users\\foo\\Projects\\mi-proyecto\\src\\main.py") == "mi-proyecto"
    
    # Path UNIX con 'Projects' en mayúsculas
    assert detect_project("/Users/foo/Projects/otro-proyecto/main.py") == "otro-proyecto"
    
    # Path sin projects
    assert detect_project("/Users/foo/documentos/main.py") is None
