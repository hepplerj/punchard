import github_sync


def _item(number, reason="assigned", title="T", repo="chnm/timer", is_pr=False):
    return {
        "gh_repo": repo, "gh_number": number,
        "gh_url": f"https://github.com/{repo}/issues/{number}",
        "gh_type": "pr" if is_pr else "issue",
        "gh_reason": reason, "title": title,
    }


def test_insert_new(raw_db):
    summary = github_sync.reconcile(raw_db, [_item(1)])
    assert summary["added"] == 1
    row = raw_db.execute("SELECT * FROM tasks WHERE gh_number=1").fetchone()
    assert row["source"] == "github" and row["status"] == "open"
    assert row["assigned_to_me"] == 1 and row["project_id"] is None


def test_auto_map_project_on_insert(raw_db, seed_project):
    pid = seed_project()
    raw_db.execute("INSERT INTO repo_project_map (repo, project_id) VALUES ('chnm/timer', ?)", (pid,))
    raw_db.commit()
    github_sync.reconcile(raw_db, [_item(1)])
    row = raw_db.execute("SELECT project_id FROM tasks WHERE gh_number=1").fetchone()
    assert row["project_id"] == pid


def test_manual_project_preserved_on_resync(raw_db, seed_project):
    pid = seed_project()
    github_sync.reconcile(raw_db, [_item(1)])
    raw_db.execute("UPDATE tasks SET project_id=? WHERE gh_number=1", (pid,))
    raw_db.commit()
    github_sync.reconcile(raw_db, [_item(1, title="changed")])
    row = raw_db.execute("SELECT project_id, title FROM tasks WHERE gh_number=1").fetchone()
    assert row["project_id"] == pid
    assert row["title"] == "changed"


def test_vanished_task_marked_done(raw_db):
    github_sync.reconcile(raw_db, [_item(1), _item(2)])
    summary = github_sync.reconcile(raw_db, [_item(1)])
    assert summary["closed"] == 1
    row = raw_db.execute("SELECT status, done_at FROM tasks WHERE gh_number=2").fetchone()
    assert row["status"] == "done" and row["done_at"] is not None
    assert raw_db.execute("SELECT status FROM tasks WHERE gh_number=1").fetchone()["status"] == "open"


def test_reappearing_task_reopens(raw_db):
    github_sync.reconcile(raw_db, [_item(1)])
    github_sync.reconcile(raw_db, [])  # 1 vanishes -> done
    assert raw_db.execute("SELECT status FROM tasks WHERE gh_number=1").fetchone()["status"] == "done"
    github_sync.reconcile(raw_db, [_item(1)])  # comes back
    row = raw_db.execute("SELECT status, done_at FROM tasks WHERE gh_number=1").fetchone()
    assert row["status"] == "open" and row["done_at"] is None


def test_adhoc_untouched_by_sync(raw_db):
    raw_db.execute("INSERT INTO tasks (source, title, status) VALUES ('adhoc', 'mine', 'open')")
    raw_db.commit()
    github_sync.reconcile(raw_db, [])  # empty github results
    assert raw_db.execute("SELECT status FROM tasks WHERE source='adhoc'").fetchone()["status"] == "open"


def test_browse_added_task_survives_sync(raw_db):
    # A browse-added task: github source, assigned_to_me=0, not returned by fetch_mine.
    raw_db.execute("INSERT INTO tasks (source, title, status, gh_repo, gh_number, gh_url, gh_type, assigned_to_me) "
                   "VALUES ('github', 'Stray', 'open', 'chnm/bar', 3, 'u', 'issue', 0)")
    raw_db.commit()
    github_sync.reconcile(raw_db, [])  # my sync returns nothing
    row = raw_db.execute("SELECT status FROM tasks WHERE gh_number=3").fetchone()
    assert row["status"] == "open"
