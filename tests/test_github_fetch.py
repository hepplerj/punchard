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


def test_queries_exclude_archived_repos(monkeypatch):
    seen = []

    def fake_get(url, headers, params, timeout):
        seen.append(params["q"])
        return FakeResp(200, {"items": []})

    monkeypatch.setattr(github_sync.requests, "get", fake_get)
    github_sync.fetch_mine("tok", "chnm")
    github_sync.fetch_all_open("tok", "chnm")
    assert seen, "expected search queries to be issued"
    assert all("archived:false" in q for q in seen)
