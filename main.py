"""FastAPI app and routes."""

import hashlib
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

from credits import total_credits
from db import get_conn, init_db, new_id
from runner import execute_run


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AgentRunLoop", lifespan=lifespan)


class CreateRunRequest(BaseModel):
    goal: str
    credit_budget: int


def request_hash(body: CreateRunRequest) -> str:
    """sha256 of a normalized JSON encoding of the request body.

    Normalized means sorted keys and no incidental whitespace, so two requests
    that differ only in key order or formatting hash the same. Only the fields
    that define the work belong here — adding a timestamp or a client-generated
    id would make every retry look like a changed body.
    """
    payload = json.dumps(
        {"goal": body.goal, "credit_budget": body.credit_budget},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def serialize_run(conn: sqlite3.Connection, run: sqlite3.Row) -> dict:
    """Shared response shape for both endpoints.

    credits_used is always summed from the ledger; there is no column to read.
    """
    steps = conn.execute(
        "SELECT id, step_index, status, tool_name, tool_output, attempt_count"
        " FROM steps WHERE run_id = ? ORDER BY step_index",
        (run["id"],),
    ).fetchall()
    return {
        "id": run["id"],
        "status": run["status"],
        "credit_budget": run["credit_budget"],
        "credits_used": total_credits(conn, run["id"]),
        "output": run["output"],
        "steps": [dict(s) for s in steps],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/runs")
def create_run(
    body: CreateRunRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header required")

    incoming_hash = request_hash(body)
    conn = get_conn()
    try:
        # Insert first, ask questions later. No SELECT-then-INSERT: the UNIQUE
        # index on idempotency_key is the thing that decides who wins, and it
        # decides atomically. See the conflict branch below.
        try:
            run_id = new_id()
            conn.execute(
                "INSERT INTO runs (id, idempotency_key, goal, request_hash,"
                " status, credit_budget, output, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    run_id,
                    idempotency_key,
                    body.goal,
                    incoming_hash,
                    "PENDING",
                    body.credit_budget,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            # Only an idempotency_key collision is a retry. Any other integrity
            # failure is a bug and must surface, not be reported as a duplicate.
            if "runs.idempotency_key" not in str(exc):
                raise
            conn.rollback()

            existing = conn.execute(
                "SELECT * FROM runs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing["request_hash"] != incoming_hash:
                # Same key, different body: the client reused a key for new
                # work. Returning the old run would silently drop their request.
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key already used with a different request body",
                )
            # Same key, same body: hand back the run the first call created.
            response.status_code = 200
            return serialize_run(conn, existing)

        # Fresh insert only. The retry branch above returns before reaching
        # here, so a retried request never launches a second loop against a
        # run that is already executing.
        background_tasks.add_task(execute_run, run_id)

        response.status_code = 201
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return serialize_run(conn, run)
    finally:
        conn.close()


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    conn = get_conn()
    try:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return serialize_run(conn, run)
    finally:
        conn.close()
