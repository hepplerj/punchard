# GitHub Tasks Inbox — Design

**Date:** 2026-07-01
**Status:** Approved (pending spec review)

## Summary

Add a **task inbox** layer to the Punchcard time tracker. Today the app only
records *time already spent* (projects → entries). This adds *things to do*:
GitHub issues and pull requests from the `chnm` org that are assigned to me or
awaiting my review, plus ad hoc tasks I type in. Tasks can be assigned to a
project, and I can start a timer directly from a task.

The inbox is primarily a **planning view**. The link to timing is deliberately
light: one-click "start timer on this task," storing the task→entry link for a
future (not-yet-built) task-level time report.

**Read-only toward GitHub.** The app never mutates GitHub. Issues/PRs are closed
in GitHub by hand; the app notices on the next sync and marks the task done.

## Goals

- See open GitHub issues + PRs that are mine (assigned or review-requested) in
  one place, grouped by project.
- Add ad hoc tasks and assign them to a project.
- Assign GitHub tasks to projects with minimal repeated triage (hybrid
  auto-mapping by repo).
- Start a timer from a task in one click, with the resulting entry linked back
  to the task.
- A safety net to catch org issues that *should* have been assigned to me but
  weren't.

## Non-goals (YAGNI)

- No writing back to GitHub (no closing/commenting/assigning from the app).
- No task-level time reports yet — we only store the `entry.task_id` link so
  it's a cheap future add.
- No background/scheduled sync — sync is a manual button (a CLI script is a
  possible later add, mirroring the existing importers).
- No task ordering/priority/drag-drop.
- No multi-user / auth — single-user local tool, as today.

## Data model

Follows the existing inline-migration pattern in `init_db()`
(`CREATE TABLE IF NOT EXISTS` + conditional `ALTER TABLE`).

### `tasks`
| field | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `source` | TEXT | `'github'` or `'adhoc'` |
| `project_id` | INTEGER NULL | FK → projects(id); nullable until triaged |
| `title` | TEXT | issue/PR title or ad hoc text |
| `status` | TEXT | `'open'` / `'done'`, default `'open'` |
| `gh_repo` | TEXT NULL | e.g. `chnm/timer` (null for ad hoc) |
| `gh_number` | INTEGER NULL | issue/PR number |
| `gh_url` | TEXT NULL | html_url for link-out |
| `gh_type` | TEXT NULL | `'issue'` or `'pr'` |
| `gh_reason` | TEXT NULL | `'assigned'` or `'review'` |
| `assigned_to_me` | INTEGER | 1/0 |
| `created_at` | TEXT | default localtime |
| `done_at` | TEXT NULL | |

- **Unique index on `(gh_repo, gh_number)`** so re-syncing upserts rather than
  duplicating. (Ad hoc rows have NULL repo/number; SQLite treats NULLs as
  distinct, so multiple ad hoc rows are fine.)

### `repo_project_map`
| field | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `repo` | TEXT UNIQUE | e.g. `chnm/timer` |
| `project_id` | INTEGER | FK → projects(id) |

The memory behind hybrid auto-mapping: repo → default project.

### `entries.task_id` (new column)
Nullable INTEGER, FK → tasks(id). Set when a timer is started from a task. The
"bit of C" link; enables a future hours-per-task report.

## GitHub sync

### Config
- `GITHUB_TOKEN` — a Personal Access Token with read access to org repos, read
  from the environment at sync time. Never committed.
- `GITHUB_ORG` — defaults to `chnm`.
- Both documented in the README; `.env` remains gitignored. Using `@me` in the
  search query means the username is not hardcoded.

### Queries
A `POST /tasks/sync` route calls GitHub's search API (`GET /search/issues`)
server-side with `requests`, running two queries and unioning the results (both
issues and PRs are returned by these):

1. `org:chnm is:open assignee:@me`
2. `org:chnm is:open review-requested:@me`

Each result row maps to a task: `gh_type` from whether the item has a
`pull_request` key, `gh_reason` from which query it came from (assigned wins if
in both), `assigned_to_me = 1`, `project_id` auto-filled from
`repo_project_map` if the repo is known, else NULL.

### Upsert + reconcile
- **Upsert** by `(gh_repo, gh_number)`: insert new, update title/url/reason on
  existing, and reset `status='open'` / clear `done_at` if a previously-done
  task reappears in the results (it was reopened on GitHub). Never overwrite a
  `project_id` the user has manually set.
- **Reconcile:** any GitHub task previously `open` that is *not* in the fresh
  union = closed or un-assigned on GitHub → set `status='done'`, `done_at=now`.
  This is how "close it in GitHub, the app notices" works.
- Ad hoc tasks are never touched by sync.

### The "everything" safety net (on-demand, not stored)
The stored inbox holds only what's mine. To catch issues that *should* have been
assigned to me, a separate view queries `org:chnm is:open` **live** when opened,
lists results (title, repo, link, assignees), and offers a one-click "add as
task" that inserts it as a normal GitHub task. Nothing from this view is
persisted until I explicitly pull it in. Keeps the inbox clean and the DB small.

### Error handling
The sync route catches missing/invalid token, network errors, and GitHub API
errors (incl. rate limits), and renders an error banner on the inbox — it never
crashes the request. The live "everything" view degrades the same way.

## Inbox UI

New **Tasks** nav item (`templates/tasks.html`, matching existing template
conventions and `static/style.css` palette/mono variables).

- **Sync from GitHub** button with last-synced time; error banner slot.
- **Add task** form — title + project dropdown (ad hoc).
- **Task list**, grouped by project (with an "unassigned" group), each row:
  - title; source badge (`issue #42` / `PR #7` / `ad hoc`); assigned-vs-review
    tag for GitHub rows.
  - **project dropdown** to assign/reassign.
  - **▸ start timer** button (disabled until the task has a project).
  - **done** checkbox (ad hoc only — GitHub rows are closed in GitHub).
  - GitHub rows link out to `gh_url`.
- **Filters:** mine / everything, by project, hide done.

**Hybrid mapping in action:** assigning a GitHub task from a not-yet-mapped repo
to a project upserts that `repo → project` mapping, so the next issue from that
repo auto-lands there. Reassigning updates the mapping.

Mutations are form POSTs that redirect, consistent with the rest of the app
(no API endpoints). Alpine.js handles inline toggles as elsewhere.

## Timer link (the "bit of C")

A `POST /tasks/<id>/start` route: stops any running timer (same as `/start`),
inserts an entry with `project_id` = the task's project, `note` prefilled with
the title (+ `#number` for GitHub tasks), and `task_id` = the task id. Only
available once the task has a project (entries require a non-null `project_id`).
Redirects to the dashboard so the live timer shows, as today.

## Dependencies

- Add `requests` to `pyproject.toml` dependencies (via `uv add requests`).

## Testing

Structure sync so the GitHub **fetch** (network) is separate from the **upsert +
reconcile** (DB logic). The reconcile step is a pure-ish function
`(existing_tasks, fresh_api_items) -> planned changes` that can be unit-tested
with fixture payloads and a mocked fetch — this is the trickiest bit and where
regressions would hide (e.g. a task wrongly marked done, a manual project
assignment clobbered). Also test:
- New issue with a known repo mapping auto-assigns the project.
- Manual `project_id` survives a re-sync.
- A task dropping out of results is marked done; re-appearing reopens it.
- Ad hoc tasks are untouched by sync.
- Start-timer requires a project and links `entry.task_id`.

## Open questions

None outstanding. Section-2 "everything" decision resolved:
store-only-mine + on-demand live browse.
