import importlib
import os
import sqlite3

import pytest


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def app_module(db_path, monkeypatch):
    """Import app.py bound to a temp DB (schema created on import)."""
    monkeypatch.setenv("TIMER_DB", db_path)
    import app as app_mod
    importlib.reload(app_mod)  # re-run init_db() against the temp DB
    return app_mod


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def raw_db(app_module, db_path):
    """A direct connection to the temp DB (schema already created)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


@pytest.fixture
def seed_project(raw_db):
    """Insert a project and return its id."""
    def _make(name="Test Project", pi_name="Dr. Test"):
        cur = raw_db.execute(
            "INSERT INTO projects (name, pi_name, color) VALUES (?, ?, '#3B82F6')",
            (name, pi_name),
        )
        raw_db.commit()
        return cur.lastrowid
    return _make
