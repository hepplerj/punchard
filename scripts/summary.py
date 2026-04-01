import sqlite3
from pathlib import Path

db = sqlite3.connect(Path(__file__).parent.parent / "timer.db")
db.row_factory = sqlite3.Row

rows = db.execute("""
    SELECT p.name, p.pi_name,
           ROUND(SUM((julianday(e.stopped_at) - julianday(e.started_at)) * 24), 2) AS hours
    FROM entries e JOIN projects p ON e.project_id = p.id
    WHERE e.stopped_at IS NOT NULL
    GROUP BY p.id ORDER BY hours DESC
""").fetchall()

if not rows:
    print("No entries yet.")
else:
    print(f"{'Project':<30} {'PI':<20} {'Hours':>6}")
    print("-" * 60)
    for r in rows:
        print(f"{r['name']:<30} {r['pi_name'] or '—':<20} {r['hours']:>6.2f}")
    total = sum(r["hours"] for r in rows if r["hours"])
    print("-" * 60)
    print(f"{'Total':<51} {total:>6.2f}")
