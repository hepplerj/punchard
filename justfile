# Punchcard — dev commands

default:
    @just --list

# Start the dev server
run:
    uv run flask run --debug --port 5001

# Install dependencies
install:
    uv sync

# Open the app in the browser
open:
    open http://localhost:5001

# Reset the database (destructive!)
reset-db:
    @echo "Deleting timer.db..."
    rm -f timer.db
    @echo "Done. Database will be recreated on next run."

# Import a Clockify detailed CSV export
import-clockify file:
    uv run python scripts/import_clockify.py {{file}}

# Import from Timewarrior (reads live via `timew export`)
import-timewarrior:
    uv run python scripts/import_timewarrior.py

# Show a summary of logged hours by project (all time)
summary:
    uv run python scripts/summary.py
