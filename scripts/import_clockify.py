"""
Import a Clockify detailed time report CSV into timer.db.

Usage:
    uv run python scripts/import_clockify.py <path-to-csv>

Mapping:
    Project     -> projects.name
    Client      -> projects.pi_name
    Description -> entries.note
    Start Date + Start Time -> entries.started_at
    End Date   + End Time   -> entries.stopped_at

Projects are created automatically if they don't exist yet.
Entries with a matching (project_id, started_at) are skipped to avoid duplicates.
"""

import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

COLORS = ["#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6", "#06B6D4", "#F97316", "#EC4899"]
DB = Path(__file__).parent.parent / "timer.db"


def parse_dt(date_str, time_str):
    """Parse Clockify's MM/DD/YYYY + HH:MM:SS AM/PM into a DB-friendly string."""
    return datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %I:%M:%S %p").strftime("%Y-%m-%d %H:%M:%S")


def main(csv_path):
    if not Path(csv_path).exists():
        sys.exit(f"File not found: {csv_path}")

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    created_projects = 0
    imported = 0
    skipped = 0

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            project_name = row["Project"].strip()
            pi_name      = row["Client"].strip()
            note         = row["Description"].strip()

            # Find or create project
            project = db.execute(
                "SELECT id FROM projects WHERE name = ? COLLATE NOCASE", (project_name,)
            ).fetchone()

            if not project:
                color = COLORS[created_projects % len(COLORS)]
                db.execute(
                    "INSERT INTO projects (name, pi_name, color) VALUES (?, ?, ?)",
                    (project_name, pi_name, color),
                )
                db.commit()
                project = db.execute(
                    "SELECT id FROM projects WHERE name = ? COLLATE NOCASE", (project_name,)
                ).fetchone()
                print(f"  + Project: {project_name!r} (PI: {pi_name or '—'})")
                created_projects += 1

            # Parse timestamps
            try:
                started_at = parse_dt(row["Start Date"], row["Start Time"])
                stopped_at = parse_dt(row["End Date"],   row["End Time"])
            except (ValueError, KeyError) as e:
                print(f"  ! Skipping row (bad date): {row} — {e}")
                skipped += 1
                continue

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
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run python scripts/import_clockify.py <path-to-csv>")
    main(sys.argv[1])
