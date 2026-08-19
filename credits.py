"""Credit accounting against the ledger.

The ledger is the only record of spend: there is no credits_used column to keep
in sync, so a charge is a single INSERT and the total is always a SUM.
"""

import sqlite3
from datetime import datetime, timezone

from db import new_id


class AlreadyChargedError(Exception):
    """Raised when a step already has a ledger row.

    Callers treat this as a no-op: the charge they were trying to write is
    already in the ledger, so the work has been paid for exactly once.
    """


def charge(
    conn: sqlite3.Connection,
    run_id: str,
    step_id: str | None,
    amount: int,
    reason: str,
) -> str:
    """Insert one ledger row in the caller's transaction. Returns the row id.

    Positive amount is a charge, negative is a refund. Pass step_id=None for
    run-level entries (refunds, adjustments) that are not tied to one step —
    the UNIQUE index permits any number of NULLs.

    Does not commit. Raises AlreadyChargedError if step_id is already charged.
    """
    entry_id = new_id()
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO credit_ledger (id, run_id, step_id, amount, reason,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (entry_id, run_id, step_id, amount, reason, created_at),
        )
    except sqlite3.IntegrityError as exc:
        # IntegrityError also covers FK violations (bad run_id/step_id) and NOT
        # NULL failures. Those are bugs, not duplicates — translating them into
        # AlreadyChargedError would make callers swallow a charge that never
        # landed, so only the step_id UNIQUE collision is remapped.
        if "credit_ledger.step_id" in str(exc):
            raise AlreadyChargedError(
                f"step {step_id} already has a ledger entry"
            ) from exc
        raise
    return entry_id


def total_credits(conn: sqlite3.Connection, run_id: str) -> int:
    """Total spend for a run: charges minus refunds.

    COALESCE matters — SUM over zero rows is NULL, not 0, and a run that has not
    been charged yet must compare against a budget as 0.
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM credit_ledger"
        " WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row["total"])
