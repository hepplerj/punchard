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

## Stack

Flask, SQLite, Alpine.js, Observable Plot. No build step. Single `timer.db` file for all data.
