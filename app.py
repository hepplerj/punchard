import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, url_for

app = Flask(__name__)
DATABASE = Path(__file__).parent / "timer.db"

COLORS = ["#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6", "#06B6D4", "#F97316", "#EC4899"]


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DATABASE) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                pi_name    TEXT NOT NULL DEFAULT '',
                color      TEXT NOT NULL DEFAULT '#3B82F6',
                active     INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER NOT NULL REFERENCES projects(id),
                started_at  TEXT NOT NULL,
                stopped_at  TEXT,
                note        TEXT NOT NULL DEFAULT '',
                is_meeting  INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS allocations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                label      TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date   TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS allocation_entries (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                allocation_id INTEGER NOT NULL REFERENCES allocations(id),
                pi_name       TEXT NOT NULL,
                percentage    REAL NOT NULL
            );
        """)
        # Migration: add is_meeting to existing databases
        cols = [r[1] for r in db.execute("PRAGMA table_info(entries)").fetchall()]
        if "is_meeting" not in cols:
            db.execute("ALTER TABLE entries ADD COLUMN is_meeting INTEGER NOT NULL DEFAULT 0")


init_db()


def ts_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_unix(dt_str):
    """Convert a local datetime string to a Unix timestamp for JS."""
    return int(datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").timestamp())


# ---------------------------------------------------------------------------
# Routes — dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    db = get_db()
    projects = db.execute(
        "SELECT * FROM projects WHERE active = 1 ORDER BY pi_name, name"
    ).fetchall()

    active_entry = db.execute("""
        SELECT e.*, p.name AS project_name, p.color AS project_color
        FROM entries e JOIN projects p ON e.project_id = p.id
        WHERE e.stopped_at IS NULL
        LIMIT 1
    """).fetchone()

    today = datetime.now().strftime("%Y-%m-%d")
    today_entries = db.execute("""
        SELECT e.*, p.name AS project_name, p.color AS project_color,
               ROUND(
                 (julianday(COALESCE(e.stopped_at,
                   strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')))
                  - julianday(e.started_at)) * 24, 2
               ) AS hours
        FROM entries e JOIN projects p ON e.project_id = p.id
        WHERE date(e.started_at) = ?
        ORDER BY e.started_at ASC
    """, (today,)).fetchall()

    today_total = sum(r["hours"] for r in today_entries if r["hours"])

    started_ts = to_unix(active_entry["started_at"]) if active_entry else None

    return render_template(
        "index.html",
        projects=projects,
        active_entry=active_entry,
        started_ts=started_ts,
        today_entries=today_entries,
        today_total=today_total,
        today=today,
    )


@app.route("/start", methods=["POST"])
def start():
    db = get_db()
    db.execute("UPDATE entries SET stopped_at = ? WHERE stopped_at IS NULL", (ts_now(),))
    db.execute(
        "INSERT INTO entries (project_id, started_at, note, is_meeting) VALUES (?, ?, ?, ?)",
        (request.form["project_id"], ts_now(), request.form.get("note", ""), 1 if request.form.get("is_meeting") else 0),
    )
    db.commit()
    return redirect(url_for("index"))


@app.route("/stop", methods=["POST"])
def stop():
    db = get_db()
    db.execute("UPDATE entries SET stopped_at = ? WHERE stopped_at IS NULL", (ts_now(),))
    db.commit()
    return redirect(url_for("index"))


@app.route("/entries/new", methods=["POST"])
def new_entry():
    db = get_db()
    date = request.form["date"]
    started_at = f"{date} {request.form['start_time']}:00"
    stop_time = request.form.get("stop_time", "").strip()
    stopped_at = f"{date} {stop_time}:00" if stop_time else None
    db.execute(
        "INSERT INTO entries (project_id, started_at, stopped_at, note, is_meeting) VALUES (?, ?, ?, ?, ?)",
        (request.form["project_id"], started_at, stopped_at, request.form.get("note", ""), 1 if request.form.get("is_meeting") else 0),
    )
    db.commit()
    return redirect(url_for("index"))


@app.route("/entries/<int:entry_id>/edit", methods=["POST"])
def edit_entry(entry_id):
    db = get_db()
    date = request.form["date"]
    started_at = f"{date} {request.form['start_time']}:00"
    stop_time = request.form.get("stop_time", "").strip()
    stopped_at = f"{date} {stop_time}:00" if stop_time else None
    db.execute(
        "UPDATE entries SET project_id = ?, started_at = ?, stopped_at = ?, note = ?, is_meeting = ? WHERE id = ?",
        (request.form["project_id"], started_at, stopped_at, request.form.get("note", ""), 1 if request.form.get("is_meeting") else 0, entry_id),
    )
    db.commit()
    back = request.form.get("back", "index")
    return redirect(url_for(back))


@app.route("/entries/<int:entry_id>/delete", methods=["POST"])
def delete_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    db.commit()
    back = request.form.get("back", "index")
    return redirect(url_for(back))


# ---------------------------------------------------------------------------
# Routes — entries log
# ---------------------------------------------------------------------------

@app.route("/entries")
def entries():
    db = get_db()
    projects = db.execute("SELECT * FROM projects ORDER BY pi_name, name").fetchall()

    # Filters
    project_id = request.args.get("project_id", "")
    meeting_only = request.args.get("meeting_only", "")
    start = request.args.get("start", "")
    end = request.args.get("end", "")

    where = ["e.stopped_at IS NOT NULL"]
    params = []
    if project_id:
        where.append("e.project_id = ?")
        params.append(project_id)
    if meeting_only:
        where.append("e.is_meeting = 1")
    if start:
        where.append("date(e.started_at) >= ?")
        params.append(start)
    if end:
        where.append("date(e.started_at) <= ?")
        params.append(end)

    rows = db.execute(f"""
        SELECT e.*, p.name AS project_name, p.color AS project_color,
               ROUND((julianday(e.stopped_at) - julianday(e.started_at)) * 24, 2) AS hours
        FROM entries e JOIN projects p ON e.project_id = p.id
        WHERE {' AND '.join(where)}
        ORDER BY e.started_at DESC
    """, params).fetchall()

    return render_template("entries.html", entries=rows, projects=projects,
                           project_id=project_id, meeting_only=meeting_only,
                           start=start, end=end)


# ---------------------------------------------------------------------------
# Routes — projects
# ---------------------------------------------------------------------------

@app.route("/projects")
def projects():
    db = get_db()
    rows = db.execute("""
        SELECT p.*,
               COUNT(e.id) AS entry_count,
               ROUND(SUM(
                 CASE WHEN e.stopped_at IS NOT NULL
                   THEN (julianday(e.stopped_at) - julianday(e.started_at)) * 24
                   ELSE 0 END
               ), 1) AS total_hours
        FROM projects p
        LEFT JOIN entries e ON p.id = e.project_id
        GROUP BY p.id
        ORDER BY p.name
    """).fetchall()
    return render_template("projects.html", projects=rows, colors=COLORS)


@app.route("/projects/new", methods=["POST"])
def new_project():
    db = get_db()
    db.execute(
        "INSERT INTO projects (name, pi_name, color) VALUES (?, ?, ?)",
        (
            request.form["name"].strip(),
            request.form.get("pi_name", "").strip(),
            request.form.get("color", COLORS[0]),
        ),
    )
    db.commit()
    return redirect(url_for("projects"))


@app.route("/projects/<int:project_id>/edit", methods=["POST"])
def edit_project(project_id):
    db = get_db()
    db.execute(
        "UPDATE projects SET name = ?, pi_name = ?, color = ? WHERE id = ?",
        (
            request.form["name"].strip(),
            request.form.get("pi_name", "").strip(),
            request.form.get("color", COLORS[0]),
            project_id,
        ),
    )
    db.commit()
    return redirect(url_for("projects"))


@app.route("/projects/<int:project_id>/toggle", methods=["POST"])
def toggle_project(project_id):
    db = get_db()
    db.execute("UPDATE projects SET active = NOT active WHERE id = ?", (project_id,))
    db.commit()
    return redirect(url_for("projects"))


@app.route("/projects/<int:project_id>/delete", methods=["POST"])
def delete_project(project_id):
    db = get_db()
    db.execute("DELETE FROM entries WHERE project_id = ?", (project_id,))
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    return redirect(url_for("projects"))


# ---------------------------------------------------------------------------
# Routes — report
# ---------------------------------------------------------------------------

@app.route("/report")
def report():
    db = get_db()
    now = datetime.now()
    q_month = ((now.month - 1) // 3) * 3 + 1
    default_start = f"{now.year}-{q_month:02d}-01"
    default_end = now.strftime("%Y-%m-%d")

    start = request.args.get("start", default_start)
    end = request.args.get("end", default_end)

    rows = db.execute("""
        SELECT p.name, p.pi_name, p.color,
               ROUND(SUM(
                 (julianday(e.stopped_at) - julianday(e.started_at)) * 24
               ), 2) AS hours,
               ROUND(SUM(
                 CASE WHEN e.is_meeting = 1
                   THEN (julianday(e.stopped_at) - julianday(e.started_at)) * 24
                   ELSE 0 END
               ), 2) AS meeting_hours
        FROM entries e JOIN projects p ON e.project_id = p.id
        WHERE e.stopped_at IS NOT NULL
          AND date(e.started_at) BETWEEN ? AND ?
        GROUP BY p.id
        ORDER BY hours DESC
    """, (start, end)).fetchall()

    total = sum(r["hours"] for r in rows if r["hours"])
    total_meeting = sum(r["meeting_hours"] for r in rows if r["meeting_hours"])

    chart_data = json.dumps({
        "labels": [r["name"] for r in rows],
        "data": [float(r["hours"] or 0) for r in rows],
        "meeting": [float(r["meeting_hours"] or 0) for r in rows],
        "colors": [r["color"] for r in rows],
    })

    # Find allocation period that best overlaps this date range
    allocation = db.execute("""
        SELECT * FROM allocations
        WHERE start_date <= ? AND end_date >= ?
        ORDER BY start_date DESC LIMIT 1
    """, (end, start)).fetchone()

    alloc_comparison = None
    alloc_chart_data = None
    if allocation:
        alloc_entries = db.execute("""
            SELECT pi_name, percentage FROM allocation_entries
            WHERE allocation_id = ? ORDER BY percentage DESC
        """, (allocation["id"],)).fetchall()

        if alloc_entries:
            # Aggregate actual hours by PI
            pi_hours = db.execute("""
                SELECT p.pi_name,
                       ROUND(SUM(
                         (julianday(e.stopped_at) - julianday(e.started_at)) * 24
                       ), 2) AS hours
                FROM entries e JOIN projects p ON e.project_id = p.id
                WHERE e.stopped_at IS NOT NULL
                  AND date(e.started_at) BETWEEN ? AND ?
                GROUP BY p.pi_name
            """, (start, end)).fetchall()

            pi_hours_map = {r["pi_name"]: float(r["hours"] or 0) for r in pi_hours}

            comparison = []
            for ae in alloc_entries:
                actual = pi_hours_map.pop(ae["pi_name"], 0.0)
                actual_pct = (actual / total * 100) if total > 0 else 0
                comparison.append({
                    "pi_name":    ae["pi_name"],
                    "target_pct": ae["percentage"],
                    "actual_hrs": actual,
                    "actual_pct": round(actual_pct, 1),
                    "delta":      round(actual_pct - ae["percentage"], 1),
                })

            # Any PIs with hours but no allocation
            for pi, hrs in pi_hours_map.items():
                if hrs > 0:
                    actual_pct = (hrs / total * 100) if total > 0 else 0
                    comparison.append({
                        "pi_name":    pi or "(unassigned)",
                        "target_pct": 0,
                        "actual_hrs": hrs,
                        "actual_pct": round(actual_pct, 1),
                        "delta":      round(actual_pct, 1),
                    })

            alloc_comparison = {
                "label":   allocation["label"],
                "start":   allocation["start_date"],
                "end":     allocation["end_date"],
                "entries": comparison,
            }

            alloc_chart_data = json.dumps({
                "labels":  [c["pi_name"] or "(unassigned)" for c in comparison],
                "target":  [c["target_pct"] for c in comparison],
                "actual":  [c["actual_pct"] for c in comparison],
            })

    return render_template(
        "report.html",
        rows=rows,
        start=start,
        end=end,
        total=total,
        total_meeting=total_meeting,
        chart_data=chart_data,
        alloc_comparison=alloc_comparison,
        alloc_chart_data=alloc_chart_data,
    )


# ---------------------------------------------------------------------------
# Routes — allocations
# ---------------------------------------------------------------------------

@app.route("/allocations")
def allocations():
    db = get_db()
    allocs = db.execute("SELECT * FROM allocations ORDER BY start_date DESC").fetchall()
    result = []
    for a in allocs:
        entries = db.execute("""
            SELECT * FROM allocation_entries
            WHERE allocation_id = ? ORDER BY percentage DESC
        """, (a["id"],)).fetchall()
        total_pct = sum(e["percentage"] for e in entries)
        result.append({"alloc": a, "entries": entries, "total_pct": total_pct})

    pi_names = [r[0] for r in db.execute(
        "SELECT DISTINCT pi_name FROM projects WHERE pi_name != '' ORDER BY pi_name"
    ).fetchall()]

    return render_template("allocations.html", allocations=result, pi_names=pi_names)


@app.route("/allocations/new", methods=["POST"])
def new_allocation():
    db = get_db()
    db.execute(
        "INSERT INTO allocations (label, start_date, end_date) VALUES (?, ?, ?)",
        (request.form["label"].strip(), request.form["start_date"], request.form["end_date"]),
    )
    alloc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Always reserve 20% for professional development
    db.execute(
        "INSERT INTO allocation_entries (allocation_id, pi_name, percentage) VALUES (?, ?, ?)",
        (alloc_id, "Professional Development", 20),
    )
    db.commit()
    return redirect(url_for("allocations"))


@app.route("/allocations/<int:alloc_id>/delete", methods=["POST"])
def delete_allocation(alloc_id):
    db = get_db()
    db.execute("DELETE FROM allocation_entries WHERE allocation_id = ?", (alloc_id,))
    db.execute("DELETE FROM allocations WHERE id = ?", (alloc_id,))
    db.commit()
    return redirect(url_for("allocations"))


@app.route("/allocations/<int:alloc_id>/entries/new", methods=["POST"])
def new_allocation_entry(alloc_id):
    db = get_db()
    db.execute(
        "INSERT INTO allocation_entries (allocation_id, pi_name, percentage) VALUES (?, ?, ?)",
        (alloc_id, request.form["pi_name"].strip(), float(request.form["percentage"])),
    )
    db.commit()
    return redirect(url_for("allocations"))


@app.route("/allocations/entries/<int:entry_id>/delete", methods=["POST"])
def delete_allocation_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM allocation_entries WHERE id = ?", (entry_id,))
    db.commit()
    return redirect(url_for("allocations"))


# ---------------------------------------------------------------------------
# Routes — calendar
# ---------------------------------------------------------------------------

@app.route("/calendar")
def calendar():
    db = get_db()
    today = datetime.now().date()

    week_str = request.args.get("week")
    if week_str:
        week_start = datetime.strptime(week_str, "%Y-%m-%d").date()
    else:
        week_start = today - timedelta(days=today.weekday())  # Monday

    week_end = week_start + timedelta(days=6)

    rows = db.execute("""
        SELECT e.*, p.name AS project_name, p.color AS project_color
        FROM entries e JOIN projects p ON e.project_id = p.id
        WHERE date(e.started_at) BETWEEN ? AND ?
        ORDER BY e.started_at
    """, (week_start.isoformat(), week_end.isoformat())).fetchall()

    # 1 px per minute, display 6:00–22:00 (960 px total)
    DISPLAY_START = 6 * 60
    DISPLAY_END   = 22 * 60

    def to_min(dt_str):
        t = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return t.hour * 60 + t.minute

    days = []
    for i in range(7):
        day_date = week_start + timedelta(days=i)
        blocks = []
        for row in rows:
            if row["started_at"][:10] != day_date.isoformat():
                continue
            start_min = to_min(row["started_at"])
            if row["stopped_at"]:
                end_min = to_min(row["stopped_at"])
            else:
                n = datetime.now()
                end_min = n.hour * 60 + n.minute
            start_c = max(DISPLAY_START, min(DISPLAY_END, start_min))
            end_c   = max(DISPLAY_START, min(DISPLAY_END, end_min))
            if end_c <= start_c:
                continue
            blocks.append({
                "id":           row["id"],
                "project_name": row["project_name"],
                "color":        row["project_color"],
                "note":         row["note"],
                "start_label":  row["started_at"][11:16],
                "end_label":    row["stopped_at"][11:16] if row["stopped_at"] else None,
                "top_px":       start_c - DISPLAY_START,
                "height_px":    max(end_c - start_c, 22),
            })
        days.append({
            "date":     day_date,
            "label":    day_date.strftime("%a"),
            "num":      day_date.strftime("%-d"),
            "is_today": day_date == today,
            "entries":  blocks,
        })

    return render_template(
        "calendar.html",
        days=days,
        week_start=week_start,
        week_end=week_end,
        prev_week=(week_start - timedelta(days=7)).isoformat(),
        next_week=(week_start + timedelta(days=7)).isoformat(),
        today_week=today - timedelta(days=today.weekday()),
        hours=list(range(6, 22)),
        display_start=DISPLAY_START,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
