# AgentRunLoop

Minimal FastAPI + SQLite scaffold. Python 3.11+, standard-library `sqlite3` only —
no ORM, no migrations.

## Run

```bash
./run.sh
curl localhost:8000/health   # {"status":"ok"}
```

`run.sh` creates `.venv` on first run, installs `requirements.txt`, and starts
uvicorn on port 8000 with `--reload`.

## Layout

| File               | Purpose                                    |
| ------------------ | ------------------------------------------ |
| `main.py`          | FastAPI app, lifespan startup, routes      |
| `db.py`            | `get_conn()` + `init_db()` schema stub     |
| `requirements.txt` | fastapi, uvicorn                           |
| `run.sh`           | install + serve                            |

The database is a single file, `agent.db`, created next to `db.py`.

## Two SQLite defaults worth overriding

`db.get_conn()` sets both on every connection:

- **`row_factory = sqlite3.Row`** — by default `sqlite3` yields plain tuples, so
  reads become positional (`row[0]`) and silently break when a column is added or
  reordered. `sqlite3.Row` gives dict-like access by name (`row["status"]`) and
  still supports indexing, at effectively no cost.
- **`PRAGMA foreign_keys = ON`** — SQLite ships with foreign-key enforcement
  **off** for backwards compatibility. Without it, `REFERENCES` clauses parse and
  are then ignored: orphan rows and dangling references are accepted. The pragma
  is **per-connection**, not stored in the file, so it must be re-issued on each
  new connection — which is why it lives in `get_conn()` rather than `init_db()`.
