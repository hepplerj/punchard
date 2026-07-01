def test_new_adhoc_task(client, seed_project, raw_db):
    pid = seed_project()
    client.post("/tasks/new", data={"title": "Read paper", "project_id": str(pid)})
    row = raw_db.execute("SELECT * FROM tasks WHERE title='Read paper'").fetchone()
    assert row["source"] == "adhoc" and row["project_id"] == pid


def test_assign_remembers_repo_mapping(client, seed_project, raw_db):
    pid = seed_project()
    raw_db.execute("INSERT INTO tasks (source, title, status, gh_repo, gh_number, assigned_to_me) "
                   "VALUES ('github', 'X', 'open', 'chnm/foo', 5, 1)")
    raw_db.commit()
    tid = raw_db.execute("SELECT id FROM tasks WHERE gh_number=5").fetchone()["id"]
    client.post(f"/tasks/{tid}/assign", data={"project_id": str(pid)})
    mapping = raw_db.execute("SELECT project_id FROM repo_project_map WHERE repo='chnm/foo'").fetchone()
    assert mapping["project_id"] == pid
    assert raw_db.execute("SELECT project_id FROM tasks WHERE id=?", (tid,)).fetchone()["project_id"] == pid


def test_toggle_done(client, raw_db):
    raw_db.execute("INSERT INTO tasks (source, title, status) VALUES ('adhoc', 'T', 'open')")
    raw_db.commit()
    tid = raw_db.execute("SELECT id FROM tasks WHERE title='T'").fetchone()["id"]
    client.post(f"/tasks/{tid}/done")
    assert raw_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()["status"] == "done"
    client.post(f"/tasks/{tid}/done")
    assert raw_db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()["status"] == "open"


def test_start_timer_from_task_links_entry(client, seed_project, raw_db):
    pid = seed_project()
    raw_db.execute("INSERT INTO tasks (source, project_id, title, status, gh_repo, gh_number) "
                   "VALUES ('github', ?, 'Fix bug', 'open', 'chnm/foo', 9)", (pid,))
    raw_db.commit()
    tid = raw_db.execute("SELECT id FROM tasks WHERE gh_number=9").fetchone()["id"]
    resp = client.post(f"/tasks/{tid}/start")
    assert resp.status_code == 302
    entry = raw_db.execute("SELECT * FROM entries WHERE stopped_at IS NULL").fetchone()
    assert entry["project_id"] == pid and entry["task_id"] == tid
    assert "chnm/foo#9" in entry["note"]


def test_start_timer_requires_project(client, raw_db):
    raw_db.execute("INSERT INTO tasks (source, title, status) VALUES ('adhoc', 'no project', 'open')")
    raw_db.commit()
    tid = raw_db.execute("SELECT id FROM tasks WHERE title='no project'").fetchone()["id"]
    client.post(f"/tasks/{tid}/start")
    assert raw_db.execute("SELECT COUNT(*) c FROM entries").fetchone()["c"] == 0
