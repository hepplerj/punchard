# GitHub Tasks Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a task inbox to the Punchcard time tracker that pulls GitHub issues/PRs assigned to me (or awaiting my review) from the `chnm` org, lets me add ad hoc tasks, assigns tasks to projects, and starts a timer from a task.

**Architecture:** GitHub network calls, item parsing, and DB upsert/reconcile live in a new `github_sync.py` module so the tricky logic is unit-testable without Flask or the network. `app.py` gains routes that orchestrate that module and render server-side Jinja templates, consistent with the existing form-POST-then-redirect style. The app never writes to GitHub; issues closed on GitHub are detected as "missing from the sync" and marked done locally.

**Tech Stack:** Python 3, Flask, SQLite (stdlib `sqlite3`), `requests` (new), `python-dotenv` (new, for loading `.env`), `pytest` (new, dev), Alpine.js (CDN, already present), Jinja2.

## Global Constraints

- Single-file Flask app style: routes in `app.py`, no API endpoints — all mutations are form POSTs that redirect.
- SQLite at `timer.db`. Timestamps are local datetime strings `YYYY-MM-DD HH:MM:SS`. Use the existing `ts_now()` helper.
- Schema changes go in `init_db()` using `CREATE TABLE IF NOT EXISTS` + conditional `ALTER TABLE`, matching the existing `is_meeting` migration.
- Config from environment: `GITHUB_TOKEN` (required at sync time), `GITHUB_ORG` (default `chnm`). Never commit `.env` (already gitignored).
- Templates extend `base.html`, import the `project_select` macro from `macros.html`, and reuse existing CSS classes (`.card`, `.section-header`, `.btn`, `.btn-primary`, `.btn-ghost`, `.btn-sm`, `.muted`, `.project-dot`, `.meeting-badge`, `.form-row`, `.form-group`, `.empty-state`).
- Tests point at a temporary DB via the `TIMER_DB` env var; never touch the real `timer.db`.

---

### Task 1: Test infra, dependencies, and configurable DB path

Sets up pytest and the two runtime deps, and makes the DB path overridable so tests never touch the real database. Everything downstream depends on this.

**Files:**
- Modify: `pyproject.toml` (add deps + pytest config)
- Modify: `app.py:9` (make `DATABASE` honor `TIMER_DB`; load `.env`)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Modify: `justfile` (add `test` recipe)

**Interfaces:**
- Produces: `app.py` reads `DATABASE` from `os.environ["TIMER_DB"]` when set. Fixtures `raw_db` (a `sqlite3.Connection` to a temp DB with the full schema) and `client` (Flask test client bound to a temp DB) available to all tests.

- [ ] **Step 1: Add dependencies**

Run:
```bash
uv add requests python-dotenv
uv add --dev pytest
```
Expected: `pyproject.toml` gains `requests` and `python-dotenv` under dependencies and `pytest` under dev; `uv.lock` updates.

- [ ] **Step 2: Add pytest config to `pyproject.toml`**

Append this section to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 3: Make `DATABASE` configurable and load `.env` in `app.py`**

At the top of `app.py`, change the imports and `DATABASE` line. Replace:
```python
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, url_for

app = Flask(__name__)
DATABASE = Path(__file__).parent / "timer.db"
```
with:
```python
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, redirect, render_template, request, url_for

load_dotenv()

app = Flask(__name__)
DATABASE = Path(os.environ.get("TIMER_DB") or (Path(__file__).parent / "timer.db"))
```

- [ ] **Step 4: Create `tests/__init__.py`**

Create an empty file at `tests/__init__.py`.

- [ ] **Step 5: Write `tests/conftest.py`**

```python
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
```

- [ ] **Step 6: Add `test` recipe to `justfile`**

Add under the existing recipes:
```
# Run the test suite
test:
    uv run pytest
```

- [ ] **Step 7: Verify the harness runs**

Run: `uv run pytest`
Expected: PASS with "no tests ran" (exit 0, collected 0 items) — confirms pytest, config, and imports work.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock app.py tests/__init__.py tests/conftest.py justfile
git commit -m "chore: add pytest, requests, python-dotenv; configurable TIMER_DB"
```

---

### Task 2: Database schema for tasks, repo mapping, meta, and entry link

Adds the three new tables and the `entries.task_id` column via inline migrations.

**Files:**
- Modify: `app.py` inside `init_db()` (lines ~36-70)
- Create: `tests/test_schema.py`

**Interfaces:**
- Produces: tables `tasks`, `repo_project_map`, `meta`, and column `entries.task_id`. Task columns: `id, source, project_id, title, status, gh_repo, gh_number, gh_url, gh_type, gh_reason, assigned_to_me, created_at, done_at`. Unique index `ux_tasks_gh` on `(gh_repo, gh_number)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_schema.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schema.py -v`
Expected: FAIL (no such table: tasks).

- [ ] **Step 3: Add the schema in `init_db()`**

Inside the `db.executescript(""" ... """)` call in `init_db()`, add these tables after the `allocation_entries` table (before the closing `"""`):
```sql
            CREATE TABLE IF NOT EXISTS tasks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                source         TEXT NOT NULL,
                project_id     INTEGER REFERENCES projects(id),
                title          TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'open',
                gh_repo        TEXT,
                gh_number      INTEGER,
                gh_url         TEXT,
                gh_type        TEXT,
                gh_reason      TEXT,
                assigned_to_me INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                done_at        TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_gh ON tasks(gh_repo, gh_number);
            CREATE TABLE IF NOT EXISTS repo_project_map (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                repo       TEXT NOT NULL UNIQUE,
                project_id INTEGER NOT NULL REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
```

Then, after the existing `is_meeting` migration block, add the `task_id` migration:
```python
        # Migration: add task_id to entries
        ecols = [r[1] for r in db.execute("PRAGMA table_info(entries)").fetchall()]
        if "task_id" not in ecols:
            db.execute("ALTER TABLE entries ADD COLUMN task_id INTEGER REFERENCES tasks(id)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_schema.py
git commit -m "feat: schema for tasks, repo mapping, meta, and entry.task_id"
```

---

### Task 3: `parse_item` and `merge_items` (pure GitHub payload mapping)

Pure functions mapping GitHub search API items into task dicts. No network, no DB.

**Files:**
- Create: `github_sync.py`
- Create: `tests/test_github_parse.py`

**Interfaces:**
- Produces:
  - `parse_item(raw: dict, reason: str) -> dict` returning keys `gh_repo, gh_number, gh_url, gh_type, gh_reason, title`. `gh_type` is `"pr"` if the raw item has a `pull_request` key else `"issue"`. `gh_repo` is the `owner/name` slice of `repository_url`.
  - `merge_items(assigned: list, review: list) -> list` — union keyed by `(gh_repo, gh_number)`, where an item in `assigned` wins over the same item in `review`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_github_parse.py`:
```python
import github_sync


def _raw(number, is_pr=False, title="T"):
    d = {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/chnm/timer/issues/{number}",
        "repository_url": "https://api.github.com/repos/chnm/timer",
    }
    if is_pr:
        d["pull_request"] = {"url": "..."}
    return d


def test_parse_issue():
    t = github_sync.parse_item(_raw(42), "assigned")
    assert t == {
        "gh_repo": "chnm/timer", "gh_number": 42,
        "gh_url": "https://github.com/chnm/timer/issues/42",
        "gh_type": "issue", "gh_reason": "assigned", "title": "T",
    }


def test_parse_pr_detected():
    t = github_sync.parse_item(_raw(7, is_pr=True), "review")
    assert t["gh_type"] == "pr"
    assert t["gh_reason"] == "review"


def test_merge_assigned_wins():
    assigned = [github_sync.parse_item(_raw(1), "assigned")]
    review = [github_sync.parse_item(_raw(1), "review"),
              github_sync.parse_item(_raw(2), "review")]
    merged = {(m["gh_repo"], m["gh_number"]): m for m in
              github_sync.merge_items(assigned, review)}
    assert len(merged) == 2
    assert merged[("chnm/timer", 1)]["gh_reason"] == "assigned"
    assert merged[("chnm/timer", 2)]["gh_reason"] == "review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_github_parse.py -v`
Expected: FAIL (No module named 'github_sync').

- [ ] **Step 3: Create `github_sync.py` with the pure functions**

```python
"""GitHub issue/PR sync for the Punchcard task inbox.

Read-only: fetches issues/PRs from the configured org via the GitHub search
API and reconciles them into the local `tasks` table. Never writes to GitHub.
"""

import os

import requests

API = "https://api.github.com/search/issues"


class GitHubError(Exception):
    pass


def parse_item(raw, reason):
    """Map a GitHub search API item to a task dict.

    reason is 'assigned' or 'review'.
    """
    repo = raw["repository_url"].split("/repos/", 1)[1]
    return {
        "gh_repo": repo,
        "gh_number": raw["number"],
        "gh_url": raw["html_url"],
        "gh_type": "pr" if "pull_request" in raw else "issue",
        "gh_reason": reason,
        "title": raw["title"],
    }


def merge_items(assigned, review):
    """Union of two parsed lists keyed by (repo, number); assigned wins."""
    by_key = {}
    for it in review:
        by_key[(it["gh_repo"], it["gh_number"])] = it
    for it in assigned:
        by_key[(it["gh_repo"], it["gh_number"])] = it
    return list(by_key.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github_parse.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add github_sync.py tests/test_github_parse.py
git commit -m "feat: github_sync parse_item and merge_items"
```

---

### Task 4: `reconcile` (upsert + mark-done + auto-map) — the core

Upserts parsed GitHub items into `tasks`, auto-assigns projects from `repo_project_map` on insert, preserves manually-set projects, reopens reappearing tasks, and marks vanished tasks done. This is the highest-risk logic; test it thoroughly.

**Files:**
- Modify: `github_sync.py`
- Create: `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `parse_item`, a `tasks`/`repo_project_map` schema (Task 2), a `sqlite3.Connection`.
- Produces: `reconcile(db, items: list) -> dict` returning `{"added": int, "updated": int, "closed": int}`. Commits the connection. Only affects `source='github'` rows.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reconcile.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reconcile.py -v`
Expected: FAIL (module has no attribute 'reconcile').

- [ ] **Step 3: Implement `reconcile` in `github_sync.py`**

Append to `github_sync.py`:
```python
def reconcile(db, items):
    """Upsert GitHub tasks; mark previously-open ones now missing as done.

    Never overwrites a manually-set project_id. Auto-assigns project from
    repo_project_map on first insert. Reopens a done task that reappears.
    Returns {"added", "updated", "closed"}.
    """
    seen = set()
    added = updated = 0
    for it in items:
        key = (it["gh_repo"], it["gh_number"])
        seen.add(key)
        existing = db.execute(
            "SELECT id FROM tasks WHERE gh_repo=? AND gh_number=?", key
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE tasks SET title=?, gh_url=?, gh_type=?, gh_reason=?, "
                "assigned_to_me=1, status='open', done_at=NULL WHERE id=?",
                (it["title"], it["gh_url"], it["gh_type"], it["gh_reason"], existing["id"]),
            )
            updated += 1
        else:
            mapped = db.execute(
                "SELECT project_id FROM repo_project_map WHERE repo=?",
                (it["gh_repo"],),
            ).fetchone()
            db.execute(
                "INSERT INTO tasks (source, project_id, title, status, gh_repo, "
                "gh_number, gh_url, gh_type, gh_reason, assigned_to_me) "
                "VALUES ('github', ?, ?, 'open', ?, ?, ?, ?, ?, 1)",
                (mapped["project_id"] if mapped else None, it["title"],
                 it["gh_repo"], it["gh_number"], it["gh_url"], it["gh_type"],
                 it["gh_reason"]),
            )
            added += 1

    closed = 0
    open_gh = db.execute(
        "SELECT id, gh_repo, gh_number FROM tasks "
        "WHERE source='github' AND status='open'"
    ).fetchall()
    for row in open_gh:
        if (row["gh_repo"], row["gh_number"]) not in seen:
            db.execute(
                "UPDATE tasks SET status='done', "
                "done_at=strftime('%Y-%m-%d %H:%M:%S','now','localtime') WHERE id=?",
                (row["id"],),
            )
            closed += 1

    db.commit()
    return {"added": added, "updated": updated, "closed": closed}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reconcile.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add github_sync.py tests/test_reconcile.py
git commit -m "feat: github_sync reconcile with upsert, auto-map, and mark-done"
```

---

### Task 5: Network fetchers and env config

Wraps the GitHub search API with error handling and reads config from the environment.

**Files:**
- Modify: `github_sync.py`
- Create: `tests/test_github_fetch.py`

**Interfaces:**
- Consumes: `parse_item`, `merge_items`, `requests`.
- Produces:
  - `env_config() -> (token, org)` — raises `GitHubError` if `GITHUB_TOKEN` unset; org defaults to `chnm`.
  - `fetch_mine(token, org) -> list` — merged parsed items from the assignee and review-requested searches.
  - `fetch_all_open(token, org) -> list` — up to 100 open items (dicts with `gh_repo, gh_number, gh_url, gh_type, title, assignees`), most-recently-updated first.
  - `GitHubError` raised on non-200 responses.

- [ ] **Step 1: Write the failing test**

Create `tests/test_github_fetch.py`:
```python
import pytest

import github_sync


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = "error body"

    def json(self):
        return self._payload


def test_env_config_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(github_sync.GitHubError):
        github_sync.env_config()


def test_env_config_defaults_org(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.delenv("GITHUB_ORG", raising=False)
    token, org = github_sync.env_config()
    assert token == "x" and org == "chnm"


def test_fetch_mine_merges(monkeypatch):
    def fake_get(url, headers, params, timeout):
        q = params["q"]
        if "assignee:@me" in q:
            return FakeResp(200, {"items": [{
                "number": 1, "title": "A",
                "html_url": "https://github.com/chnm/timer/issues/1",
                "repository_url": "https://api.github.com/repos/chnm/timer"}]})
        return FakeResp(200, {"items": [{
            "number": 2, "title": "B", "pull_request": {"url": "x"},
            "html_url": "https://github.com/chnm/timer/pull/2",
            "repository_url": "https://api.github.com/repos/chnm/timer"}]})
    monkeypatch.setattr(github_sync.requests, "get", fake_get)
    items = github_sync.fetch_mine("tok", "chnm")
    by_num = {i["gh_number"]: i for i in items}
    assert by_num[1]["gh_reason"] == "assigned"
    assert by_num[2]["gh_reason"] == "review" and by_num[2]["gh_type"] == "pr"


def test_fetch_raises_on_error(monkeypatch):
    monkeypatch.setattr(github_sync.requests, "get",
                        lambda *a, **k: FakeResp(401, {}))
    with pytest.raises(github_sync.GitHubError):
        github_sync.fetch_mine("tok", "chnm")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_github_fetch.py -v`
Expected: FAIL (module has no attribute 'env_config').

- [ ] **Step 3: Implement fetchers and config in `github_sync.py`**

Append to `github_sync.py`:
```python
def env_config():
    token = os.environ.get("GITHUB_TOKEN")
    org = os.environ.get("GITHUB_ORG", "chnm")
    if not token:
        raise GitHubError("GITHUB_TOKEN is not set — add it to your .env file.")
    return token, org


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _search(query, token):
    try:
        resp = requests.get(
            API, headers=_headers(token),
            params={"q": query, "per_page": 100}, timeout=15,
        )
    except requests.RequestException as e:
        raise GitHubError(f"Could not reach GitHub: {e}")
    if resp.status_code != 200:
        raise GitHubError(f"GitHub API returned {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("items", [])


def fetch_mine(token, org):
    assigned = [parse_item(r, "assigned")
                for r in _search(f"org:{org} is:open assignee:@me", token)]
    review = [parse_item(r, "review")
              for r in _search(f"org:{org} is:open review-requested:@me", token)]
    return merge_items(assigned, review)


def fetch_all_open(token, org):
    items = []
    for r in _search(f"org:{org} is:open sort:updated-desc", token):
        items.append({
            "gh_repo": r["repository_url"].split("/repos/", 1)[1],
            "gh_number": r["number"],
            "gh_url": r["html_url"],
            "gh_type": "pr" if "pull_request" in r else "issue",
            "title": r["title"],
            "assignees": [a["login"] for a in r.get("assignees", [])],
        })
    return items
```

Note: `fetch_all_open` returns at most 100 items (one search page). This is a deliberate cap for the live "everything" browse — the template will state when 100 are shown.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github_fetch.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add github_sync.py tests/test_github_fetch.py
git commit -m "feat: github_sync fetchers and env config"
```

---

### Task 6: Inbox page and sync route

The `/tasks` page (grouped list + project/hide-done filters), the sync button wiring, an error/success banner, and the nav link.

**Files:**
- Modify: `app.py` (add `import github_sync`; add `tasks` and `tasks_sync` routes)
- Create: `templates/tasks.html`
- Modify: `templates/base.html:17` (add nav link)
- Create: `tests/test_tasks_page.py`

**Interfaces:**
- Consumes: `github_sync.env_config`, `fetch_mine`, `reconcile`; `ts_now()`.
- Produces: `GET /tasks` (endpoint `tasks`), `POST /tasks/sync` (endpoint `tasks_sync`). Template `tasks.html` renders rows with `task-row` markup relied on by Task 7.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tasks_page.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tasks_page.py -v`
Expected: FAIL (404 for /tasks).

- [ ] **Step 3: Add `import github_sync` and the routes to `app.py`**

Add `import github_sync` with the other imports. Add these routes (place them after the entries-log section, before the projects section):
```python
# ---------------------------------------------------------------------------
# Routes — tasks
# ---------------------------------------------------------------------------

@app.route("/tasks")
def tasks():
    db = get_db()
    projects = db.execute(
        "SELECT * FROM projects WHERE active = 1 ORDER BY pi_name, name"
    ).fetchall()

    project_id = request.args.get("project_id", "")
    hide_done = request.args.get("hide_done", "1")

    where = []
    params = []
    if project_id:
        where.append("t.project_id = ?")
        params.append(project_id)
    if hide_done:
        where.append("t.status = 'open'")
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    rows = db.execute(f"""
        SELECT t.*, p.name AS project_name, p.color AS project_color
        FROM tasks t LEFT JOIN projects p ON t.project_id = p.id
        {clause}
        ORDER BY (t.project_id IS NULL), p.pi_name, p.name,
                 t.status, t.gh_type, t.gh_number, t.id
    """, params).fetchall()

    last_sync = db.execute(
        "SELECT value FROM meta WHERE key = 'github_last_sync'"
    ).fetchone()

    return render_template(
        "tasks.html",
        tasks=rows,
        projects=projects,
        project_id=project_id,
        hide_done=hide_done,
        last_sync=last_sync["value"] if last_sync else None,
        synced=request.args.get("synced"),
        error=request.args.get("error"),
    )


@app.route("/tasks/sync", methods=["POST"])
def tasks_sync():
    db = get_db()
    try:
        token, org = github_sync.env_config()
        items = github_sync.fetch_mine(token, org)
        summary = github_sync.reconcile(db, items)
        db.execute(
            "INSERT INTO meta (key, value) VALUES ('github_last_sync', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (ts_now(),),
        )
        db.commit()
        msg = (f"Synced: {summary['added']} new, "
               f"{summary['updated']} updated, {summary['closed']} closed.")
        return redirect(url_for("tasks", synced=msg))
    except github_sync.GitHubError as e:
        return redirect(url_for("tasks", error=str(e)))
```

- [ ] **Step 4: Add the nav link in `base.html`**

After the Entries nav link (line ~17), add:
```html
      <a href="/tasks" {% if request.endpoint in ('tasks', 'tasks_browse') %}class="active"{% endif %}>Tasks</a>
```

- [ ] **Step 5: Create `templates/tasks.html`**

```html
{% extends "base.html" %}
{% from "macros.html" import project_select %}
{% block title %}Tasks — Punchcard{% endblock %}

{% block content %}

<div class="section-header">
  <h2>Tasks</h2>
  <div style="display:flex;gap:.5rem;align-items:center">
    {% if last_sync %}<span class="muted">Last synced {{ last_sync }}</span>{% endif %}
    <a href="/tasks/browse" class="btn btn-ghost btn-sm">Browse org</a>
    <form action="/tasks/sync" method="post" class="inline-form">
      <button type="submit" class="btn btn-primary btn-sm">Sync from GitHub</button>
    </form>
  </div>
</div>

{% if error %}<div class="card" style="border-color:#EF4444"><p class="muted">⚠ {{ error }}</p></div>{% endif %}
{% if synced %}<div class="card"><p class="muted">✓ {{ synced }}</p></div>{% endif %}

{# ── Add ad hoc task ── #}
<div class="card">
  <form action="/tasks/new" method="post" class="form-row">
    <div class="form-group" style="flex:2">
      <label>New task</label>
      <input type="text" name="title" placeholder="Ad hoc task…" required>
    </div>
    <div class="form-group" style="flex:2">
      <label>Project</label>
      {{ project_select(projects, required=False, include_all=True) }}
    </div>
    <div class="form-group" style="justify-content:flex-end">
      <button type="submit" class="btn btn-primary btn-sm">Add</button>
    </div>
  </form>
</div>

{# ── Filters ── #}
<div class="card">
  <form method="get" action="/tasks" class="filter-form">
    <div class="form-row">
      <div class="form-group" style="flex:2">
        <label>Project</label>
        {{ project_select(projects, selected=project_id, required=False, include_all=True) }}
      </div>
      <div class="form-group form-group-check">
        <label class="check-label">
          <input type="checkbox" name="hide_done" value="1" {% if hide_done %}checked{% endif %}>
          <span>Hide done</span>
        </label>
      </div>
      <div class="form-group" style="justify-content:flex-end">
        <div style="display:flex;gap:.5rem">
          <button type="submit" class="btn btn-primary btn-sm">Filter</button>
          <a href="/tasks" class="btn btn-ghost btn-sm">Reset</a>
        </div>
      </div>
    </div>
  </form>
</div>

{% if tasks %}
<div class="entries-log">
  {% set ns = namespace(current='__start__') %}
  {% for t in tasks %}
    {% set group = t.project_name or "Unassigned" %}
    {% if group != ns.current %}
      {% if ns.current != '__start__' %}</div>{% endif %}
      {% set ns.current = group %}
      <div class="entries-day-group">
      <div class="entries-day-header"><span>{{ group }}</span></div>
    {% endif %}

    <div class="entry-row {% if t.status == 'done' %}muted{% endif %}">
      {% if t.project_color %}<span class="project-dot" style="background:{{ t.project_color }}"></span>{% endif %}

      {% if t.source == 'github' %}
        <a href="{{ t.gh_url }}" target="_blank" class="entry-note">{{ t.title }}</a>
        <span class="meeting-badge">{{ t.gh_type }} #{{ t.gh_number }}</span>
        <span class="muted">{{ t.gh_reason }}</span>
      {% else %}
        <span class="entry-project">{{ t.title }}</span>
        <span class="meeting-badge">ad hoc</span>
      {% endif %}

      <span style="flex:1"></span>

      {# assign / reassign project #}
      <form action="/tasks/{{ t.id }}/assign" method="post" class="inline-form">
        {{ project_select(projects, selected=t.project_id, required=False, include_all=True) }}
        <button type="submit" class="btn btn-ghost btn-sm">Assign</button>
      </form>

      {# start timer (needs a project) #}
      <form action="/tasks/{{ t.id }}/start" method="post" class="inline-form">
        <button type="submit" class="btn btn-ghost btn-sm"
                {% if not t.project_id or t.status == 'done' %}disabled{% endif %}
                title="Start timer">▸</button>
      </form>

      {% if t.source == 'adhoc' %}
      <form action="/tasks/{{ t.id }}/done" method="post" class="inline-form">
        <button type="submit" class="btn btn-ghost btn-sm" title="Toggle done">
          {% if t.status == 'done' %}↺{% else %}✓{% endif %}
        </button>
      </form>
      {% endif %}
    </div>
  {% endfor %}
  </div>
</div>
{% else %}
<p class="muted empty-state">No tasks. Sync from GitHub or add an ad hoc task above.</p>
{% endif %}

{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_tasks_page.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add app.py templates/tasks.html templates/base.html tests/test_tasks_page.py
git commit -m "feat: tasks inbox page and GitHub sync route"
```

---

### Task 7: Task mutation routes — new, assign, done, start timer

The ad hoc create, project assign (with repo→project mapping memory), done toggle, and start-timer routes.

**Files:**
- Modify: `app.py` (add four routes)
- Create: `tests/test_task_actions.py`

**Interfaces:**
- Consumes: `ts_now()`, the `tasks`/`repo_project_map`/`entries` schema.
- Produces: `POST /tasks/new`, `POST /tasks/<id>/assign`, `POST /tasks/<id>/done`, `POST /tasks/<id>/start`. Each redirects to `request.referrer` (falling back to the tasks page), except `start` which redirects to the dashboard.

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_actions.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_actions.py -v`
Expected: FAIL (404 for /tasks/new).

- [ ] **Step 3: Implement the four routes in `app.py`**

Add after the `tasks_sync` route:
```python
@app.route("/tasks/new", methods=["POST"])
def new_task():
    db = get_db()
    pid = request.form.get("project_id") or None
    db.execute(
        "INSERT INTO tasks (source, project_id, title, status, assigned_to_me) "
        "VALUES ('adhoc', ?, ?, 'open', 0)",
        (pid, request.form["title"].strip()),
    )
    db.commit()
    return redirect(request.referrer or url_for("tasks"))


@app.route("/tasks/<int:task_id>/assign", methods=["POST"])
def assign_task(task_id):
    db = get_db()
    pid = request.form.get("project_id") or None
    db.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (pid, task_id))
    if pid:
        row = db.execute("SELECT gh_repo FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row and row["gh_repo"]:
            db.execute(
                "INSERT INTO repo_project_map (repo, project_id) VALUES (?, ?) "
                "ON CONFLICT(repo) DO UPDATE SET project_id = excluded.project_id",
                (row["gh_repo"], pid),
            )
    db.commit()
    return redirect(request.referrer or url_for("tasks"))


@app.route("/tasks/<int:task_id>/done", methods=["POST"])
def toggle_task_done(task_id):
    db = get_db()
    row = db.execute(
        "SELECT status FROM tasks WHERE id = ? AND source = 'adhoc'", (task_id,)
    ).fetchone()
    if row:
        if row["status"] == "open":
            db.execute("UPDATE tasks SET status='done', done_at=? WHERE id=?", (ts_now(), task_id))
        else:
            db.execute("UPDATE tasks SET status='open', done_at=NULL WHERE id=?", (task_id,))
        db.commit()
    return redirect(request.referrer or url_for("tasks"))


@app.route("/tasks/<int:task_id>/start", methods=["POST"])
def start_task(task_id):
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task or not task["project_id"]:
        return redirect(request.referrer or url_for("tasks"))
    db.execute("UPDATE entries SET stopped_at = ? WHERE stopped_at IS NULL", (ts_now(),))
    note = task["title"]
    if task["gh_repo"]:
        note = f"{task['title']} ({task['gh_repo']}#{task['gh_number']})"
    db.execute(
        "INSERT INTO entries (project_id, started_at, note, is_meeting, task_id) "
        "VALUES (?, ?, ?, 0, ?)",
        (task["project_id"], ts_now(), note, task_id),
    )
    db.commit()
    return redirect(url_for("index"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_task_actions.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_task_actions.py
git commit -m "feat: task new/assign/done/start-timer routes"
```

---

### Task 8: Live "everything" org browse

The on-demand `/tasks/browse` page that queries the org's open issues live (nothing stored) and a one-click "add as task" that pulls one into the inbox.

**Files:**
- Modify: `app.py` (add `tasks_browse` and `browse_add` routes)
- Create: `templates/tasks_browse.html`
- Create: `tests/test_browse.py`

**Interfaces:**
- Consumes: `github_sync.env_config`, `fetch_all_open`; `repo_project_map`.
- Produces: `GET /tasks/browse` (endpoint `tasks_browse`), `POST /tasks/browse/add` (endpoint `browse_add`). Added tasks get `assigned_to_me=0`, auto-mapped project if the repo is known, and are deduped via the `ux_tasks_gh` unique index.

- [ ] **Step 1: Write the failing test**

Create `tests/test_browse.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_browse.py -v`
Expected: FAIL (404 for /tasks/browse).

- [ ] **Step 3: Implement the routes in `app.py`**

Add after `start_task`:
```python
@app.route("/tasks/browse")
def tasks_browse():
    try:
        token, org = github_sync.env_config()
        items = github_sync.fetch_all_open(token, org)
    except github_sync.GitHubError as e:
        return render_template("tasks_browse.html", items=[], error=str(e))

    db = get_db()
    tracked = {
        (r["gh_repo"], r["gh_number"])
        for r in db.execute(
            "SELECT gh_repo, gh_number FROM tasks WHERE source = 'github'"
        ).fetchall()
    }
    for it in items:
        it["tracked"] = (it["gh_repo"], it["gh_number"]) in tracked
    return render_template("tasks_browse.html", items=items, error=None)


@app.route("/tasks/browse/add", methods=["POST"])
def browse_add():
    db = get_db()
    repo = request.form["gh_repo"]
    mapped = db.execute(
        "SELECT project_id FROM repo_project_map WHERE repo = ?", (repo,)
    ).fetchone()
    db.execute(
        "INSERT INTO tasks (source, project_id, title, status, gh_repo, "
        "gh_number, gh_url, gh_type, assigned_to_me) "
        "VALUES ('github', ?, ?, 'open', ?, ?, ?, ?, 0) "
        "ON CONFLICT(gh_repo, gh_number) DO NOTHING",
        (mapped["project_id"] if mapped else None, request.form["title"],
         repo, request.form["gh_number"], request.form["gh_url"],
         request.form["gh_type"]),
    )
    db.commit()
    return redirect(request.referrer or url_for("tasks_browse"))
```

- [ ] **Step 4: Create `templates/tasks_browse.html`**

```html
{% extends "base.html" %}
{% block title %}Browse org — Punchcard{% endblock %}

{% block content %}

<div class="section-header">
  <h2>Browse org issues</h2>
  <a href="/tasks" class="btn btn-ghost btn-sm">← Back to tasks</a>
</div>

{% if error %}
<div class="card" style="border-color:#EF4444"><p class="muted">⚠ {{ error }}</p></div>
{% else %}
<div class="card"><p class="muted">
  Live view of open issues/PRs in the org (up to 100, most recently updated).
  Nothing here is saved until you add it.
</p></div>

{% if items %}
<div class="entries-log">
  <div class="entries-day-group">
  {% for it in items %}
    <div class="entry-row">
      <a href="{{ it.gh_url }}" target="_blank" class="entry-note">{{ it.title }}</a>
      <span class="meeting-badge">{{ it.gh_repo }} {{ it.gh_type }} #{{ it.gh_number }}</span>
      {% if it.assignees %}<span class="muted">→ {{ it.assignees|join(", ") }}</span>{% endif %}
      <span style="flex:1"></span>
      {% if it.tracked %}
        <span class="muted">already tracked</span>
      {% else %}
        <form action="/tasks/browse/add" method="post" class="inline-form">
          <input type="hidden" name="gh_repo" value="{{ it.gh_repo }}">
          <input type="hidden" name="gh_number" value="{{ it.gh_number }}">
          <input type="hidden" name="gh_type" value="{{ it.gh_type }}">
          <input type="hidden" name="gh_url" value="{{ it.gh_url }}">
          <input type="hidden" name="title" value="{{ it.title }}">
          <button type="submit" class="btn btn-ghost btn-sm">+ Add</button>
        </form>
      {% endif %}
    </div>
  {% endfor %}
  </div>
</div>
{% else %}
<p class="muted empty-state">No open issues found in the org.</p>
{% endif %}
{% endif %}

{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_browse.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add app.py templates/tasks_browse.html tests/test_browse.py
git commit -m "feat: live org browse and add-as-task"
```

---

### Task 9: Full suite, live smoke test, and docs

Confirm the whole suite is green, verify against the running server, and document setup.

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md` (commands + a line on the tasks feature)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest`
Expected: PASS (all tests from Tasks 1–8 green).

- [ ] **Step 2: Live smoke test against the running server**

The dev server runs on port 5001. With a real `GITHUB_TOKEN` in `.env`, restart it (`just run`) so `.env` and the new code load, then:
- Visit `http://localhost:5001/tasks`, click **Sync from GitHub**, confirm issues/PRs appear grouped, and the success banner shows counts.
- Assign a GitHub task to a project; confirm a second issue from the same repo auto-lands on that project after another sync.
- Click **▸** on an assigned task; confirm the dashboard shows a running timer whose note includes `repo#number`.
- Add an ad hoc task, toggle it done, confirm "Hide done" filters it.
- Open **Browse org**, confirm the live list renders and **+ Add** pulls one into the inbox.

If anything misbehaves, use `superpowers:systematic-debugging` before proceeding.

- [ ] **Step 3: Document setup in `README.md`**

Add a section:
```markdown
## GitHub task sync

The Tasks page pulls issues/PRs from a GitHub org. Configure a `.env` file
in the project root (gitignored):

```
GITHUB_TOKEN=ghp_your_personal_access_token
GITHUB_ORG=chnm
```

Create the token under your **personal** GitHub account (Settings → Developer
settings → Personal access tokens). A classic token with the `repo` scope
works; if the org enforces SSO, authorize the token for the org. The app only
reads from GitHub — close issues/PRs in GitHub and the next sync marks the
matching task done.

Click **Sync from GitHub** on the Tasks page to pull issues assigned to you
and PRs awaiting your review. **Browse org** shows a live list of all open
org issues so you can catch anything that should have been assigned to you.
```

- [ ] **Step 4: Update `CLAUDE.md`**

Under the "Key data concepts" list, add:
```markdown
- Tasks (`tasks` table) are a planning inbox: GitHub issues/PRs (synced read-only from the `chnm` org via `github_sync.py`) plus ad hoc items. A task can be assigned to a project; `repo_project_map` remembers repo→project choices. Starting a timer from a task creates an entry linked via `entries.task_id`. Closing on GitHub → task marked done on next sync.
```

Under "Import Scripts" or a new note, mention `GITHUB_TOKEN`/`GITHUB_ORG` env config and that `.env` is auto-loaded via `python-dotenv`.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document GitHub task sync setup"
```

---

## Self-Review Notes

- **Spec coverage:** data model (Task 2), sync queries + upsert/reconcile (Tasks 3–5), mine-only stored + on-demand browse (Tasks 6, 8), inbox UI + hybrid mapping (Tasks 6–7), timer link (Task 7), error handling (Tasks 5, 6, 8), deps + testing (Task 1 + tests throughout), README (Task 9). All spec sections map to a task.
- **Simplification vs spec:** the spec listed a "mine / everything" filter on the inbox list. Because the "everything" safety net is its own live `/tasks/browse` page, the stored inbox is already curated, so the inbox filters are project + hide-done only. This preserves spec intent without a redundant toggle.
- **Note format decision:** start-timer note is `title (repo#number)` for GitHub tasks, bare title for ad hoc — matches the spec's "title (+ #number)".
- **Cap disclosure:** `fetch_all_open` returns one 100-item page; the browse template states this so nothing is silently dropped.
