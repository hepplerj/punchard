# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
just run                          # Flask dev server on port 5001 (--debug)
just install                      # uv sync
just open                         # Open http://localhost:5001
just reset-db                     # Delete timer.db (recreated on next run)
just import-clockify file=X.csv   # Import Clockify detailed CSV export
just import-timewarrior           # Import from Timewarrior (calls timew export)
just summary                      # CLI table of hours by project
```

## Architecture

Single-file Flask app (`app.py`) with server-side Jinja2 rendering. No API endpoints — all mutations are form POSTs that redirect. Alpine.js (CDN) handles client-side interactivity (live timer, inline edit toggles, date presets). Observable Plot (CDN, ES module) renders report charts. No build step.

**Database:** SQLite at `timer.db` (gitignored). Two tables: `projects` and `entries`. Foreign keys enabled. Timestamps stored as local datetime strings (`YYYY-MM-DD HH:MM:SS`). A running timer is an entry with `stopped_at IS NULL`. Duration math uses `julianday()`. Schema migrations are handled inline in `init_db()` using `CREATE TABLE IF NOT EXISTS` and conditional `ALTER TABLE` checks.

**Key data concepts:**
- Projects have a `pi_name` (Principal Investigator) and `color` for chart/UI use
- Projects use soft-delete via `active` flag (archive/restore)
- Entries have an `is_meeting` boolean flag — meetings are always tied to a project, not a separate category
- Deleting a project cascades to delete its entries (manual SQL, not FK cascade)

**CSS:** Custom CSS with design variables in `static/style.css`. Warm cream/manila palette with monospace fonts (`--mono` variable) for data-heavy elements (times, hours, labels, buttons). No CSS framework.

## Import Scripts

`scripts/import_clockify.py` and `scripts/import_timewarrior.py` auto-create projects and skip duplicates (keyed on `project_id + started_at`). Timewarrior timestamps are UTC and get converted to local time. The last tag becomes the project name, preceding tags become the note.
