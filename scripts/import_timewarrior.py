"""
Import Timewarrior entries into timer.db.

Usage:
    timew export | uv run python scripts/import_timewarrior.py
    uv run python scripts/import_timewarrior.py           # reads from timew directly
    uv run python scripts/import_timewarrior.py file.json # reads from a saved export

Mapping:
    tags[-1]      -> project name  (last tag treated as project)
    tags[:-1]     -> entry note    (preceding tags, if any)
    start (UTC)   -> entries.started_at (converted to local time)
    end   (UTC)   -> entries.stopped_at (converted to local time)

Entries with no tags or no end time are skipped.
Duplicate (project_id, started_at) pairs are skipped.
"""

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

COLORS = ["#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6", "#06B6D4", "#F97316", "#EC4899"]
DB = Path(__file__).parent.parent / "timer.db"


def parse_timew_dt(s):
    """Convert '20260223T150000Z' (UTC) to local time string."""
    dt = datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def load_data(source):
    if source == "-":
        raw = sys.stdin.read()
    elif Path(source).exists():
        raw = Path(source).read_text()
    else:
        sys.exit(f"File not found: {source}")
    return json.loads(raw)


def main():
    # Determine source
    if len(sys.argv) == 2:
        data = load_data(sys.argv[1])
    elif not sys.stdin.isatty():
        data = json.loads(sys.stdin.read())
    else:
        # Call timew directly
        result = subprocess.run(["timew", "export"], capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f"timew export failed: {result.stderr}")
        data = json.loads(result.stdout)

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    created_projects = 0
    imported = 0
    skipped = 0

    for entry in data:
        tags = entry.get("tags", [])

        if not tags:
            skipped += 1
            continue

        if "end" not in entry:
            # Still running — skip
            skipped += 1
            continue

        project_name = tags[-1].strip()
        note         = ", ".join(tags[:-1]) if len(tags) > 1 else ""

        try:
            started_at = parse_timew_dt(entry["start"])
            stopped_at = parse_timew_dt(entry["end"])
        except (ValueError, KeyError) as e:
            print(f"  ! Skipping entry {entry.get('id')} (bad date): {e}")
            skipped += 1
            continue

        # Find or create project
        project = db.execute(
            "SELECT id FROM projects WHERE name = ? COLLATE NOCASE", (project_name,)
        ).fetchone()

        if not project:
            color = COLORS[created_projects % len(COLORS)]
            db.execute(
                "INSERT INTO projects (name, pi_name, color) VALUES (?, ?, ?)",
                (project_name, "", color),
            )
            db.commit()
            project = db.execute(
                "SELECT id FROM projects WHERE name = ? COLLATE NOCASE", (project_name,)
            ).fetchone()
            print(f"  + Project: {project_name!r}")
            created_projects += 1

        # Skip duplicates
        exists = db.execute(
            "SELECT 1 FROM entries WHERE project_id = ? AND started_at = ?",
            (project["id"], started_at),
        ).fetchone()
        if exists:
            skipped += 1
            continue

        db.execute(
            "INSERT INTO entries (project_id, started_at, stopped_at, note) VALUES (?, ?, ?, ?)",
            (project["id"], started_at, stopped_at, note),
        )
        imported += 1

    db.commit()
    db.close()

    print(f"\nDone. {imported} entries imported, {skipped} skipped, {created_projects} projects created.")


if __name__ == "__main__":
    main()
