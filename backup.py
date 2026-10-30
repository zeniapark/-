"""Create a consistent timestamped SQLite backup without stopping the app."""
from datetime import datetime
import os
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("CS_DB", ROOT / "data" / "cs.sqlite3")).resolve()
BACKUP_DIR = ROOT / "backups"


def main():
    if not SOURCE.is_file():
        raise SystemExit("No database was found. Start the site once before backing up.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = BACKUP_DIR / f"hanaro-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    with sqlite3.connect(SOURCE) as source, sqlite3.connect(destination) as target:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SystemExit(f"Backup integrity check failed: {result}")
    print(destination)


if __name__ == "__main__":
    main()
