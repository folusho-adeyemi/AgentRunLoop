"""Tests for credits.py against an in-memory database."""

import sqlite3
from datetime import datetime, timezone

import pytest

import db
from credits import AlreadyChargedError, charge, total_credits


@pytest.fixture
def conn():
    """In-memory db with the real schema, same pragmas as get_conn()."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    # Without this the FK in credit_ledger.step_id is not enforced, and the
    # tests would pass against a database that silently accepts orphan rows.
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(db.SCHEMA_SQL)
    yield c
    c.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def run_id(conn):
    rid = db.new_id()
    conn.execute(
        "INSERT INTO runs (id, idempotency_key, goal, request_hash, status,"
        " credit_budget, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rid, "key-" + rid, "test goal", "hash", "RUNNING", 10_000, _now()),
    )
    return rid


def make_step(conn, run_id, step_index):
    sid = db.new_id()
    conn.execute(
        "INSERT INTO steps (id, run_id, step_index, status, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (sid, run_id, step_index, "SUCCEEDED", _now()),
    )
    return sid


def test_single_charge_totals_correctly(conn, run_id):
    step_id = make_step(conn, run_id, 0)

    charge(conn, run_id, step_id, 7, "step_charge")

    assert total_credits(conn, run_id) == 7


def test_double_charge_raises_and_leaves_total_unchanged(conn, run_id):
    step_id = make_step(conn, run_id, 0)
    charge(conn, run_id, step_id, 7, "step_charge")

    with pytest.raises(AlreadyChargedError):
        charge(conn, run_id, step_id, 7, "step_charge")

    # The failed INSERT must not have landed: one step, one charge, always.
    assert total_credits(conn, run_id) == 7
    (rows,) = conn.execute(
        "SELECT COUNT(*) FROM credit_ledger WHERE step_id = ?", (step_id,)
    ).fetchone()
    assert rows == 1


def test_many_charges_sum_exactly(conn, run_id):
    amounts = [(i % 17) + 1 for i in range(500)]
    for i, amount in enumerate(amounts):
        charge(conn, run_id, make_step(conn, run_id, i), amount, "step_charge")

    # Integers all the way down — no float arithmetic anywhere in the path, so
    # this is exact equality, not approximate.
    assert total_credits(conn, run_id) == sum(amounts)
    assert isinstance(total_credits(conn, run_id), int)


def test_refund_reduces_total(conn, run_id):
    step_id = make_step(conn, run_id, 0)
    charge(conn, run_id, step_id, 10, "step_charge")

    # step_id is None: the step already has its charge row, and a refund tied to
    # the same step would collide with the UNIQUE index.
    charge(conn, run_id, None, -4, "refund")

    assert total_credits(conn, run_id) == 6


def test_charge_does_not_commit(conn, run_id):
    """The caller owns the transaction — charge() only writes, never commits."""
    step_id = make_step(conn, run_id, 0)
    charge(conn, run_id, step_id, 5, "step_charge")

    conn.rollback()

    assert total_credits(conn, run_id) == 0


def test_unrelated_integrity_errors_are_not_masked(conn, run_id):
    """A bad FK is a bug, not a duplicate; it must not become a no-op."""
    with pytest.raises(sqlite3.IntegrityError) as exc:
        charge(conn, run_id, "no-such-step", 5, "step_charge")
    assert not isinstance(exc.value, AlreadyChargedError)


def test_total_is_zero_for_run_with_no_ledger_rows(conn, run_id):
    assert total_credits(conn, run_id) == 0
