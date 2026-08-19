# AgentRunLoop

Minimal FastAPI + SQLite scaffold. Python 3.11+, standard-library `sqlite3` only —
no ORM, no migrations.

## Run

```bash
./run.sh
```

Then open <http://localhost:8000/> for the UI, or use the API directly:

```bash
curl localhost:8000/health                       # {"status":"ok"}
curl -X POST localhost:8000/runs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"goal":"summarize the docs","credit_budget":100}'
```

`run.sh` creates `.venv` on first run, installs `requirements.txt`, and starts
uvicorn on port 8000 with `--reload`.

## Endpoints

| Method | Path               | Notes                                            |
| ------ | ------------------ | ------------------------------------------------ |
| GET    | `/`                | Single-page UI                                    |
| GET    | `/health`          | `{"status":"ok"}`                                 |
| POST   | `/runs`            | Requires `Idempotency-Key`. 201 new, 200 replay, 422 key reused with a different body |
| GET    | `/runs/{id}`       | Run + ordered steps + `credits_used`              |
| POST   | `/runs/{id}/retry` | Resume a `FAILED` run from its checkpoint; 409 otherwise |

## Layout

| File               | Purpose                                        |
| ------------------ | ---------------------------------------------- |
| `main.py`          | FastAPI app, routes, idempotent run creation    |
| `db.py`            | `get_conn()`, `SCHEMA_SQL`, `init_db()`         |
| `credits.py`       | `charge()` / `total_credits()` over the ledger  |
| `runner.py`        | The run loop: plan → budget → execute → record  |
| `planner.py`       | Deterministic mock planner                      |
| `tools.py`         | Deterministic mock tools                        |
| `static/index.html`| Vanilla-JS UI, no build step                    |
| `test_credits.py`  | pytest, in-memory sqlite                        |

The database is a single file, `agent.db`, created next to `db.py`.

## Demo goals

The mock planner is deterministic, keyed off substrings in the goal:

| Goal contains | Behaviour                                                       |
| ------------- | --------------------------------------------------------------- |
| *(anything)*  | 3 × `web_search`, 10 credits each, then `COMPLETED`              |
| `loop`        | Never finishes — stops at `MAX_STEPS` or the budget              |
| `fail`        | Step 3 throws once, the in-loop retry recovers it                |
| `failhard`    | Step 3 outlasts the retries → `FAILED`; `/retry` resumes it      |

## [Demo](https://www.loom.com/share/29e2a5eca819434681a8fa2faf027e65)
