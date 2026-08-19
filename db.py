"""SQLite helpers: connection factory and schema initialisation.

Standard-library sqlite3 only — no ORM, no migration framework.
"""

import sqlite3
from pathlib import Path

# Single database file, resolved next to this module so the working directory
# does not change which database we open.
DB_PATH = Path(__file__).resolve().parent / "agent.db"


def get_conn() -> sqlite3.Connection:
    """Return a connection with dict-like rows and FK enforcement enabled."""
    conn = sqlite3.connect(DB_PATH)
    # Rows behave like dicts: row["id"] instead of row[0].
    conn.row_factory = sqlite3.Row
    # SQLite ships with foreign keys OFF; it is per-connection, so set it here.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they do not exist. Called once on app startup."""
    conn = get_conn()
    try:
        # Stage 1: fill in the CREATE TABLE bodies.
        #
        # conn.executescript(
        #     """
        #     CREATE TABLE IF NOT EXISTS runs (
        #     );
        #
        #     CREATE TABLE IF NOT EXISTS steps (
        #     );
        #     """
        # )
        conn.commit()
    finally:
        conn.close()
