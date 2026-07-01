# Punchcard

A minimal time tracker for project-based work. Built for tracking time across research projects with PI attribution, meeting/work separation, and simple reporting.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
just run
```

Open http://localhost:5001.

## Features

- **Dashboard** — start/stop timer with live elapsed display, quick project picker, optional notes
- **Projects** — track projects with PI names, color coding, archive/restore
- **Entries** — browse, filter, and edit all time entries; mark entries as meetings
- **Calendar** — weekly view with time blocks positioned by start/end time
- **Report** — date range reports with preset buttons (quarter, year, month), summary table with work vs meeting breakdown, horizontal bar charts via Observable Plot

## Importing Data

```bash
just import-clockify file=export.csv    # Clockify detailed CSV
just import-timewarrior                 # Reads from timew export
```

Both scripts auto-create projects and skip duplicates on reimport.

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

## Stack

Flask, SQLite, Alpine.js, Observable Plot. No build step. Single `timer.db` file for all data.
