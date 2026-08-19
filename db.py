"""SQLite helpers: connection factory and schema initialisation.

Standard-library sqlite3 only — no ORM, no migration framework.
"""

import sqlite3
import uuid
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


def new_id() -> str:
    """Primary keys are uuid4 hex strings generated here, not by SQLite."""
    return uuid.uuid4().hex


def init_db() -> None:
    """Create tables if they do not exist. Called once on app startup."""
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id              TEXT PRIMARY KEY,

                -- Prevents: the same client request creating two runs. A retry
                -- after a timeout or dropped response re-sends the same key, so
                -- the second INSERT fails and the handler returns the existing
                -- run instead of starting a duplicate one (and duplicate spend).
                idempotency_key TEXT NOT NULL UNIQUE,

                goal            TEXT NOT NULL,
                -- sha256 of the normalized request body. Paired with
                -- idempotency_key to detect a key reused with a *different*
                -- body, which is a client bug rather than a retry.
                request_hash    TEXT NOT NULL,
                -- PENDING, RUNNING, COMPLETED, FAILED, LIMIT_REACHED
                status          TEXT NOT NULL,
                credit_budget   INTEGER NOT NULL,
                -- Final result; null until the run finishes.
                output          TEXT,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS steps (
                id            TEXT PRIMARY KEY,
                run_id        TEXT NOT NULL REFERENCES runs(id),
                step_index    INTEGER NOT NULL,
                -- PENDING, RUNNING, SUCCEEDED, FAILED
                status        TEXT NOT NULL,
                tool_name     TEXT,
                tool_input    TEXT,
                tool_output   TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL,

                -- Prevents: a resume replaying a step that already exists.
                -- A worker that crashes mid-run and restarts recomputes the
                -- next index from what is already stored; if two workers pick
                -- up the same run, or one resumes from a stale index, the
                -- second INSERT for that (run, index) fails instead of forking
                -- the run into two divergent step-3s.
                UNIQUE (run_id, step_index)
            );

            CREATE TABLE IF NOT EXISTS credit_ledger (
                id         TEXT PRIMARY KEY,
                run_id     TEXT NOT NULL REFERENCES runs(id),

                -- Prevents: double-charging one step. A retry that re-executes
                -- the charge, or a resume that re-walks completed steps, hits
                -- this constraint and the second write fails rather than
                -- silently billing twice. NULL is allowed and, per SQL, NULLs
                -- are distinct in a UNIQUE index — so run-level entries with no
                -- step (refunds, adjustments) can be inserted freely.
                step_id    TEXT UNIQUE REFERENCES steps(id),

                -- Positive is a charge, negative is a refund.
                amount     INTEGER NOT NULL,
                -- step_charge, refund, etc.
                reason     TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
