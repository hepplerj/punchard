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
        "WHERE source='github' AND status='open' AND assigned_to_me=1"
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
    # archived:false skips repos that have been archived on GitHub — an archived
    # repo is a finished project, so its issues/PRs drop out of the sync (and
    # reconcile then marks any previously-synced tasks from it done).
    assigned = [parse_item(r, "assigned")
                for r in _search(f"org:{org} is:open assignee:@me archived:false", token)]
    review = [parse_item(r, "review")
              for r in _search(f"org:{org} is:open review-requested:@me archived:false", token)]
    return merge_items(assigned, review)


def fetch_all_open(token, org):
    items = []
    for r in _search(f"org:{org} is:open archived:false sort:updated-desc", token):
        items.append({
            "gh_repo": r["repository_url"].split("/repos/", 1)[1],
            "gh_number": r["number"],
            "gh_url": r["html_url"],
            "gh_type": "pr" if "pull_request" in r else "issue",
            "title": r["title"],
            "assignees": [a["login"] for a in r.get("assignees", [])],
        })
    return items
