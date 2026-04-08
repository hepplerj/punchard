"""Stop any running timer. Intended for cron at end of day."""

import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path(__file__).parent.parent / "timer.db"


def main():
    if not DB.exists():
        return

    db = sqlite3.connect(DB)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = db.execute("UPDATE entries SET stopped_at = ? WHERE stopped_at IS NULL", (now,))
    db.commit()

    if cursor.rowcount > 0:
        print(f"Stopped {cursor.rowcount} running entry at {now}")

    db.close()


if __name__ == "__main__":
    main()
