def test_tasks_page_empty(client):
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert b"Tasks" in resp.data


def test_adhoc_task_shows_on_page(client, raw_db, seed_project):
    pid = seed_project(name="Alpha")
    raw_db.execute("INSERT INTO tasks (source, project_id, title, status) "
                   "VALUES ('adhoc', ?, 'Write docs', 'open')", (pid,))
    raw_db.commit()
    resp = client.get("/tasks")
    assert b"Write docs" in resp.data


def test_hide_done_filters(client, raw_db):
    raw_db.execute("INSERT INTO tasks (source, title, status) VALUES ('adhoc', 'Done one', 'done')")
    raw_db.commit()
    assert b"Done one" not in client.get("/tasks").data          # default hides done
    assert b"Done one" in client.get("/tasks?hide_done=").data   # show all


def test_sync_without_token_shows_error(client, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    resp = client.post("/tasks/sync", follow_redirects=True)
    assert b"GITHUB_TOKEN is not set" in resp.data
