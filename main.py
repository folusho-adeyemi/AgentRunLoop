"""FastAPI app and routes."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AgentRunLoop", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}
