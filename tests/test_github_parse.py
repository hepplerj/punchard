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
