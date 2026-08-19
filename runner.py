"""The run loop: plan -> check budget -> execute -> record, until done."""

import sqlite3
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_status(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    conn.commit()


def execute_run(run_id: str) -> None:
    """Drive one run to a terminal state. Runs as a background task."""
    conn = get_conn()
    try:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return
        goal = run["goal"]
        budget = run["credit_budget"]

        _set_status(conn, run_id, "RUNNING")

        history: list[str] = []
        while True:
            step_index = len(history)
            action = mock_planner(goal, history)

            if action.get("done"):
                conn.execute(
                    "UPDATE runs SET status = ?, output = ? WHERE id = ?",
                    ("COMPLETED", action["output"], run_id),
                )
                conn.commit()
                return

            cost = action["cost"]

            # Budget check BEFORE executing. Spending is authorized here, not
            # discovered afterwards — see the notes in the summary.
            if total_credits(conn, run_id) + cost > budget:
                # Prior steps and charges stay exactly as they are; output is
                # left untouched so any partial result survives.
                _set_status(conn, run_id, "LIMIT_REACHED")
                return

            if step_index >= MAX_STEPS:
                _set_status(conn, run_id, "LIMIT_REACHED")
                return

            # Mark the step RUNNING and commit, so an observer polling GET
            # /runs/{id} can see work in flight rather than a silent gap.
            step_id = new_id()
            conn.execute(
                "INSERT INTO steps (id, run_id, step_index, status, tool_name,"
                " tool_input, tool_output, attempt_count, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, 1, ?)",
                (
                    step_id,
                    run_id,
                    step_index,
                    "RUNNING",
                    action["tool_name"],
                    action["tool_input"],
                    _now(),
                ),
            )
            conn.commit()

            # Tool runs with no transaction open. Holding one across the call
            # would keep a write lock for the tool's whole duration.
            output = mock_tool(action["tool_name"], action["tool_input"])

            # One transaction: the step becomes SUCCEEDED and the charge lands
            # together, or neither does.
            conn.execute(
                "UPDATE steps SET status = ?, tool_output = ? WHERE id = ?",
                ("SUCCEEDED", output, step_id),
            )
            try:
                credits.charge(conn, run_id, step_id, cost, "step_charge")
            except AlreadyChargedError:
                # Already paid for (a resume re-walking this step). The step
                # update still belongs in this commit.
                pass
            conn.commit()

            history.append(output)
    except Exception:
        # A crash must not leave the run stuck in RUNNING forever. Tool-level
        # adding failure handling and retries next, so a crash here is always a run-level failure.
        try:
            _set_status(conn, run_id, "FAILED")
        except Exception:
            pass
        raise
    finally:
        conn.close()
