"""The run loop: plan -> check budget -> execute -> record, until done.

The loop is resume-safe. All of its state lives in the steps table, so it
reconstructs where it was from the database rather than from memory: a fresh
run simply finds no checkpoint and starts at step 0.
"""

import sqlite3
import time
from datetime import datetime, timezone

import credits
from credits import AlreadyChargedError, total_credits
from db import get_conn, new_id
from planner import mock_planner
from tools import mock_tool

# Hard backstop, independent of credits. A planner bug that returns a
# zero-cost action forever would never trip the budget check, so step count
# is bounded separately.
MAX_STEPS = 25

# Retries of a single step *within one run*. MAX_RETRIES=2 means one initial
# attempt plus two retries, so three attempts before the run gives up.
MAX_RETRIES = 2
MAX_ATTEMPTS = MAX_RETRIES + 1
BACKOFF_SECONDS = 0.05


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_status(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    conn.commit()


def _load_checkpoint(conn: sqlite3.Connection, run_id: str):
    """Rebuild loop state from the steps table.

    Returns (history, pending) where history is the outputs of the contiguous
    SUCCEEDED steps starting at index 0, and pending is the existing
    not-SUCCEEDED step row at the resume point, or None.
    """
    rows = conn.execute(
        "SELECT * FROM steps WHERE run_id = ? ORDER BY step_index", (run_id,)
    ).fetchall()

    history: list[str] = []
    pending = None
    for row in rows:
        if row["status"] == "SUCCEEDED" and row["step_index"] == len(history):
            history.append(row["tool_output"])
        else:
            # First non-SUCCEEDED step: this is where work resumes. Anything
            # after it cannot exist, because the loop stops at the first failure.
            pending = row
            break
    return history, pending


def execute_run(run_id: str) -> None:
    """Drive one run to a terminal state. Runs as a background task.

    Used for both a fresh run and a resume — the difference is only what the
    checkpoint contains.
    """
    conn = get_conn()
    try:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return
        goal = run["goal"]
        budget = run["credit_budget"]

        # Completed steps and their charges are read back, never redone.
        history, pending = _load_checkpoint(conn, run_id)

        _set_status(conn, run_id, "RUNNING")

        while True:
            step_index = len(history)

            # The planner is deterministic, so replaying it with the restored
            # history reproduces exactly the action that was interrupted.
            action = mock_planner(goal, history)

            if action.get("done"):
                conn.execute(
                    "UPDATE runs SET status = ?, output = ? WHERE id = ?",
                    ("COMPLETED", action["output"], run_id),
                )
                conn.commit()
                return

            cost = action["cost"]

            # Budget check BEFORE executing. Charges from earlier steps —
            # including ones made in a previous attempt at this run — are
            # already in the total, so a resume cannot spend the budget twice.
            if total_credits(conn, run_id) + cost > budget:
                _set_status(conn, run_id, "LIMIT_REACHED")
                return

            if step_index >= MAX_STEPS:
                _set_status(conn, run_id, "LIMIT_REACHED")
                return

            # Reuse the failed step's row if we are resuming into it. Inserting
            # a second row for the same index would violate
            # UNIQUE (run_id, step_index) — the constraint that guarantees a
            # resume can never fork a run into two divergent step-3s.
            if pending is not None and pending["step_index"] == step_index:
                step_id = pending["id"]
                attempt = pending["attempt_count"]
                pending = None
            else:
                step_id = new_id()
                attempt = 0
                conn.execute(
                    "INSERT INTO steps (id, run_id, step_index, status, tool_name,"
                    " tool_input, tool_output, attempt_count, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, NULL, 0, ?)",
                    (
                        step_id,
                        run_id,
                        step_index,
                        "PENDING",
                        action["tool_name"],
                        action["tool_input"],
                        _now(),
                    ),
                )
                conn.commit()

            output = None
            failure = None
            # attempts_here bounds this run's retries; attempt is the persisted
            # cumulative count, which keeps rising across resumes.
            for attempts_here in range(1, MAX_ATTEMPTS + 1):
                attempt += 1
                conn.execute(
                    "UPDATE steps SET status = ?, attempt_count = ? WHERE id = ?",
                    ("RUNNING", attempt, step_id),
                )
                conn.commit()

                try:
                    # No transaction is open across the tool call.
                    output = mock_tool(
                        action["tool_name"], action["tool_input"], attempt
                    )
                    failure = None
                    break
                except Exception as exc:
                    failure = exc
                    if attempts_here < MAX_ATTEMPTS:
                        time.sleep(BACKOFF_SECONDS * attempts_here)

            if failure is not None:
                # Out of retries. Mark the step FAILED and write NO ledger
                # entry — nothing was delivered, so nothing is charged. Earlier
                # steps keep their outputs and their charges.
                conn.execute(
                    "UPDATE steps SET status = ?, tool_output = ? WHERE id = ?",
                    ("FAILED", f"error: {failure}", step_id),
                )
                conn.execute(
                    "UPDATE runs SET status = ? WHERE id = ?", ("FAILED", run_id)
                )
                conn.commit()
                return

            # One transaction: the step becomes SUCCEEDED and the charge lands
            # together, or neither does.
            conn.execute(
                "UPDATE steps SET status = ?, tool_output = ? WHERE id = ?",
                ("SUCCEEDED", output, step_id),
            )
            try:
                credits.charge(conn, run_id, step_id, cost, "step_charge")
            except AlreadyChargedError:
                # Safety net. A resume should never reach a step that is
                # already charged, but if a bug got us here the UNIQUE index on
                # credit_ledger.step_id rejects the duplicate rather than
                # billing twice. The step update still belongs in this commit.
                pass
            conn.commit()

            history.append(output)
    except Exception:
        # A crash must not leave the run stuck in RUNNING forever.
        try:
            _set_status(conn, run_id, "FAILED")
        except Exception:
            pass
        raise
    finally:
        conn.close()
