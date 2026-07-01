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
