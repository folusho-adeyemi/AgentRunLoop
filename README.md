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

## Reproducing the three scenarios i showed in the video

Everything below runs against your own endpoint. Start from a clean database so
the credit numbers are predictable:

```bash
lsof -ti:8000 | xargs kill -9 2>/dev/null; rm -f agent.db
./run.sh
```

Leave that running and open http://localhost:8000 in a browser for the visual, or
use the terminal commands below for the proof. The UI shows steps appearing live;
the terminal shows the status codes and the ledger.


### 1. A run that completes
<img width="829" height="877" alt="Screenshot 2026-08-19 at 5 38 07 AM" src="https://github.com/user-attachments/assets/fc204cad-6f41-4fa7-ba1b-4e5c39ceb813" />


```bash
KEY=$(uuidgen)
RID=$(curl -s -X POST localhost:8000/runs \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY" \
  -d '{"goal":"summarize the docs","credit_budget":100}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

sleep 1
curl -s localhost:8000/runs/$RID | python3 -m json.tool
```

Expect status `COMPLETED`, three steps, `credits_used` 30. The total is summed
from the ledger, not stored on the run:

```bash
sqlite3 agent.db \
  "SELECT step_index, amount, reason FROM credit_ledger l \
   JOIN steps s ON s.id = l.step_id \
   WHERE l.run_id='$RID' ORDER BY step_index;"
```

Three rows, ten credits each.

### 2. The retry that must not double-charge
<img width="824" height="893" alt="Screenshot 2026-08-19 at 5 38 20 AM" src="https://github.com/user-attachments/assets/987d7f7a-f2d8-4b4e-a740-eccda29c57f5" />


Reuse the exact same key and body from scenario 1:

```bash
curl -s -i -X POST localhost:8000/runs \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY" \
  -d '{"goal":"summarize the docs","credit_budget":100}' \
  | grep -E 'HTTP|"id"'
```

Expect HTTP 200 (not 201) and the same run id. Confirm nothing changed:

```bash
curl -s localhost:8000/runs/$RID \
  | python3 -c 'import sys,json;r=json.load(sys.stdin);print("status",r["status"],"credits",r["credits_used"],"steps",len(r["steps"]))'
```

Still 30 credits, still three steps. Reusing the key with a different body is a
client bug and returns 422:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/runs \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY" \
  -d '{"goal":"different goal","credit_budget":100}'
```

### 3. A step fails partway, then recovery
<img width="823" height="785" alt="Screenshot 2026-08-19 at 5 38 37 AM" src="https://github.com/user-attachments/assets/769f6069-e9da-4349-a53b-4ceecb8704dc" />


The goal must contain `failhard` so step 3 outlasts its in-run retries and the run
reaches FAILED:

```bash
KEY3=$(uuidgen)
RID3=$(curl -s -X POST localhost:8000/runs \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY3" \
  -d '{"goal":"failhard scenario","credit_budget":200}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

sleep 1
curl -s localhost:8000/runs/$RID3 \
  | python3 -c 'import sys,json;r=json.load(sys.stdin);print("status",r["status"],"credits",r["credits_used"])'

sqlite3 agent.db \
  "SELECT s.step_index, s.status, l.amount \
   FROM steps s LEFT JOIN credit_ledger l ON l.step_id = s.id \
   WHERE s.run_id='$RID3' ORDER BY s.step_index;"
```

Expect status `FAILED`, `credits_used` 30. Steps 0 to 2 are charged, step 3 is
FAILED with no charge. Now resume, which reuses the checkpointed outputs without
recharging:

```bash
curl -s -o /dev/null -w 'retry %{http_code}\n' -X POST localhost:8000/runs/$RID3/retry
sleep 1
curl -s localhost:8000/runs/$RID3 \
  | python3 -c 'import sys,json;r=json.load(sys.stdin);print("status",r["status"],"credits",r["credits_used"],"steps",len(r["steps"]))'

sqlite3 agent.db \
  "SELECT step_index, amount FROM credit_ledger l \
   JOIN steps s ON s.id = l.step_id \
   WHERE l.run_id='$RID3' ORDER BY step_index;"
```

Expect status `COMPLETED`, `credits_used` 50, and each step exactly once in the
ledger. The failure plus recovery costs the same 50 a clean run would have.

<img width="848" height="997" alt="Screenshot 2026-08-19 at 5 37 23 AM" src="https://github.com/user-attachments/assets/2b262ecc-a7b1-434d-869c-c27b42b80a82" />


### Run the tests

```bash
./.venv/bin/pytest -q
```

### If a number comes out wrong

- Scenario 1 not 30 credits: an old `agent.db` survived. Delete it and restart.
- Scenario 2 returns 201: you generated a new key instead of reusing `$KEY`.
- Scenario 3 completes instead of failing: the goal needs `failhard`, not `fail`.
  A plain `fail` is rescued by the in-run retry and reaches COMPLETED.
