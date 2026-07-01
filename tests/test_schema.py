def _cols(raw_db, table):
    return {r[1] for r in raw_db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_tasks_table_exists(raw_db):
    cols = _cols(raw_db, "tasks")
    assert {"id", "source", "project_id", "title", "status", "gh_repo",
            "gh_number", "gh_url", "gh_type", "gh_reason", "assigned_to_me",
            "created_at", "done_at"} <= cols


def test_repo_project_map_table_exists(raw_db):
    assert {"id", "repo", "project_id"} <= _cols(raw_db, "repo_project_map")


def test_meta_table_exists(raw_db):
    assert {"key", "value"} <= _cols(raw_db, "meta")


def test_entries_has_task_id(raw_db):
    assert "task_id" in _cols(raw_db, "entries")


def test_tasks_gh_unique(raw_db, seed_project):
    pid = seed_project()
    raw_db.execute(
        "INSERT INTO tasks (source, project_id, title, status, gh_repo, gh_number, assigned_to_me) "
        "VALUES ('github', ?, 'A', 'open', 'chnm/x', 1, 1)", (pid,))
    raw_db.commit()
    import sqlite3
    try:
        raw_db.execute(
            "INSERT INTO tasks (source, title, status, gh_repo, gh_number, assigned_to_me) "
            "VALUES ('github', 'dup', 'open', 'chnm/x', 1, 1)")
        raw_db.commit()
        assert False, "expected IntegrityError on duplicate (gh_repo, gh_number)"
    except sqlite3.IntegrityError:
        pass
