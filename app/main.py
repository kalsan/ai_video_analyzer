import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import db
from . import queue as job_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    job_queue.start()
    yield
    job_queue.stop()


app = FastAPI(lifespan=lifespan)


class SubmitBody(BaseModel):
    url: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/jobs")
def submit(body: SubmitBody):
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    row, enqueued = db.upsert_for_post(url)
    if enqueued:
        job_queue.enqueue(row["id"])
        return JSONResponse(status_code=202, content={"status": row["status"], "id": row["id"]})
    if row["status"] == db.STATUS_DONE:
        return JSONResponse(
            status_code=200,
            content={"status": row["status"], "id": row["id"], "result": row["result"]},
        )
    return JSONResponse(status_code=202, content={"status": row["status"], "id": row["id"]})


@app.get("/jobs")
def fetch(url: str = Query(...)):
    row = db.find_by_url(url)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown url")
    status = row["status"]
    if status == db.STATUS_DONE:
        return JSONResponse(
            status_code=200,
            content={"status": status, "id": row["id"], "result": row["result"]},
        )
    if status == db.STATUS_FAILED:
        return JSONResponse(
            status_code=422,
            content={"status": status, "id": row["id"], "error": row["error"]},
        )
    return JSONResponse(status_code=202, content={"status": status, "id": row["id"]})
