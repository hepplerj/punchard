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
