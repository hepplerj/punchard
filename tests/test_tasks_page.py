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


def test_pi_filter(client, raw_db, seed_project):
    pa = seed_project(name="Alpha", pi_name="Dr. A")
    pb = seed_project(name="Beta", pi_name="Dr. B")
    raw_db.execute("INSERT INTO tasks (source, project_id, title, status) VALUES ('adhoc', ?, 'TaskA', 'open')", (pa,))
    raw_db.execute("INSERT INTO tasks (source, project_id, title, status) VALUES ('adhoc', ?, 'TaskB', 'open')", (pb,))
    raw_db.commit()
    body = client.get("/tasks?pi_name=Dr.+A").data
    assert b"TaskA" in body and b"TaskB" not in body


def test_pi_and_project_combine(client, raw_db, seed_project):
    pa = seed_project(name="Alpha", pi_name="Dr. A")
    pb = seed_project(name="Beta", pi_name="Dr. B")
    raw_db.execute("INSERT INTO tasks (source, project_id, title, status) VALUES ('adhoc', ?, 'TaskA', 'open')", (pa,))
    raw_db.execute("INSERT INTO tasks (source, project_id, title, status) VALUES ('adhoc', ?, 'TaskB', 'open')", (pb,))
    raw_db.commit()
    # PI A combined with project Beta (which belongs to Dr. B) → no matches
    both = client.get(f"/tasks?pi_name=Dr.+A&project_id={pb}").data
    assert b"TaskA" not in both and b"TaskB" not in both
    # PI A combined with its own project Alpha → TaskA only
    match = client.get(f"/tasks?pi_name=Dr.+A&project_id={pa}").data
    assert b"TaskA" in match and b"TaskB" not in match


def test_adhoc_grouped_at_top(client, raw_db):
    raw_db.execute("INSERT INTO tasks (source, title, status, gh_repo, gh_number, gh_url, gh_type, assigned_to_me) "
                   "VALUES ('github', 'GH task', 'open', 'chnm/foo', 8, 'u', 'issue', 1)")
    raw_db.execute("INSERT INTO tasks (source, title, status) VALUES ('adhoc', 'My todo', 'open')")
    raw_db.commit()
    body = client.get("/tasks").data.decode()
    assert "Ad hoc tasks" in body and "Unassigned" in body
    # ad hoc group renders before the Unassigned (GitHub) group
    assert body.index("Ad hoc tasks") < body.index("Unassigned")


def test_sync_without_token_shows_error(client, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    resp = client.post("/tasks/sync", follow_redirects=True)
    assert b"GITHUB_TOKEN is not set" in resp.data
