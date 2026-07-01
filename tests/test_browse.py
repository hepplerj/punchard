import github_sync


def test_browse_lists_live_items(client, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(github_sync, "fetch_all_open", lambda t, o: [{
        "gh_repo": "chnm/bar", "gh_number": 3, "gh_type": "issue",
        "gh_url": "https://github.com/chnm/bar/issues/3",
        "title": "Stray issue", "assignees": ["someoneelse"]}])
    resp = client.get("/tasks/browse")
    assert b"Stray issue" in resp.data
    assert b"someoneelse" in resp.data


def test_browse_error_when_no_token(client, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    resp = client.get("/tasks/browse")
    assert resp.status_code == 200
    assert b"GITHUB_TOKEN is not set" in resp.data


def test_browse_add_inserts_task(client, raw_db):
    client.post("/tasks/browse/add", data={
        "gh_repo": "chnm/bar", "gh_number": "3", "gh_type": "issue",
        "gh_url": "https://github.com/chnm/bar/issues/3", "title": "Stray issue"})
    row = raw_db.execute("SELECT * FROM tasks WHERE gh_number=3").fetchone()
    assert row["source"] == "github" and row["assigned_to_me"] == 0
    assert row["title"] == "Stray issue"


def test_browse_add_is_idempotent(client, raw_db):
    data = {"gh_repo": "chnm/bar", "gh_number": "3", "gh_type": "issue",
            "gh_url": "https://github.com/chnm/bar/issues/3", "title": "Stray"}
    client.post("/tasks/browse/add", data=data)
    client.post("/tasks/browse/add", data=data)
    assert raw_db.execute("SELECT COUNT(*) c FROM tasks WHERE gh_number=3").fetchone()["c"] == 1
