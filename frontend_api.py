"""
Clearframe API: a thin FastAPI layer over the compliance pipeline.

Design discipline (state this in the panel):
  * One process, SQLite for state, no broker and no external infra. This is the
    demo surface, not the production topology.
  * The contract is async on purpose. Submitting a creative returns a queued id;
    the client polls for the result. In mock mode the pipeline finishes inline
    and instantly, but the shape does not change when real indexing takes 30s:
    the inline call becomes a queue plus a webhook, and nothing else moves.
  * The pipeline, decision engine and config are unchanged. The API only adds
    transport, persistence and the human-in-the-loop override.

Run:
    pip install fastapi uvicorn
    uvicorn frontend_api:app --reload      # serves http://localhost:8000
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Optional

import shutil
from typing import List

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.client import TwelveLabsClient
from src.pipeline import load_config, review_video

DB = Path(__file__).resolve().parent / "clearframe.db"
UPLOADS = Path(__file__).resolve().parent / "uploads"
UPLOADS.mkdir(exist_ok=True)
app = FastAPI(title="Clearframe API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_cfg = load_config()
_client = TwelveLabsClient()  # mock unless TL_API_KEY is set
_INDEX = "clearframe-index"


def _db():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, status TEXT, file TEXT, result TEXT)")
    return conn


class SubmitBody(BaseModel):
    file: str  # path or reference to the creative


class DecisionBody(BaseModel):
    decision: str  # APPROVE or BLOCK, from a human reviewer


def _run_pipeline(review_id: str, file: str) -> None:
    """Runs the compliance pipeline and stores the result. In production this is
    a worker resumed by the index.task.ready webhook, not a background task."""
    try:
        result = review_video(_client, _INDEX, file, _cfg)
        payload, status = result.model_dump(mode="json"), "done"
    except Exception as exc:  # surface the failure, do not swallow it
        payload, status = {"error": str(exc)}, "failed"
    with closing(_db()) as conn:
        conn.execute("UPDATE reviews SET status=?, result=? WHERE id=?", (status, json.dumps(payload), review_id))
        conn.commit()


@app.post("/api/reviews/upload")
async def upload(files: List[UploadFile] = File(...), tasks: BackgroundTasks = None):
    """Accept one or many creative files (bulk upload). Each file becomes its own
    queued review and runs through the pipeline independently. For large files a
    production build would issue presigned URLs and let the client upload straight
    to object storage, so the bytes never pass through this app server."""
    created = []
    for f in files:
        review_id = uuid.uuid4().hex[:12]
        dest = UPLOADS / f"{review_id}_{Path(f.filename).name}"
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        with closing(_db()) as conn:
            conn.execute("INSERT INTO reviews VALUES (?,?,?,?)", (review_id, "queued", f.filename, None))
            conn.commit()
        tasks.add_task(_run_pipeline, review_id, f.filename)
        created.append({"id": review_id, "file": f.filename, "status": "queued"})
    return {"submitted": len(created), "reviews": created}


@app.get("/api/reviews/summary")
def summary():
    """Batch rollup for the review dashboard: counts by verdict and by status."""
    with closing(_db()) as conn:
        rows = conn.execute("SELECT status, result FROM reviews").fetchall()
    by_verdict = {"APPROVE": 0, "REVIEW": 0, "BLOCK": 0}
    by_status = {}
    for status, result in rows:
        by_status[status] = by_status.get(status, 0) + 1
        if result:
            v = json.loads(result).get("decision")
            if v in by_verdict:
                by_verdict[v] += 1
    return {"total": len(rows), "by_verdict": by_verdict, "by_status": by_status}


@app.post("/api/reviews")
def submit(body: SubmitBody, tasks: BackgroundTasks):
    review_id = uuid.uuid4().hex[:12]
    with closing(_db()) as conn:
        conn.execute("INSERT INTO reviews VALUES (?,?,?,?)", (review_id, "queued", body.file, None))
        conn.commit()
    tasks.add_task(_run_pipeline, review_id, body.file)  # async by contract
    return {"id": review_id, "status": "queued"}


@app.get("/api/reviews")
def queue():
    with closing(_db()) as conn:
        rows = conn.execute("SELECT id, status, file, result FROM reviews").fetchall()
    out = []
    for rid, status, file, result in rows:
        r = json.loads(result) if result else {}
        out.append({"id": rid, "status": status, "file": file,
                    "verdict": r.get("decision"), "confidence": r.get("confidence")})
    return out


@app.get("/api/reviews/{review_id}")
def get_review(review_id: str):
    with closing(_db()) as conn:
        row = conn.execute("SELECT status, file, result FROM reviews WHERE id=?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown review id")
    status, file, result = row
    return {"id": review_id, "status": status, "file": file,
            "result": json.loads(result) if result else None}


@app.post("/api/reviews/{review_id}/decision")
def override(review_id: str, body: DecisionBody):
    """Human-in-the-loop override. The reviewer's call is recorded alongside the
    automated one; the automated verdict is never silently overwritten."""
    if body.decision not in ("APPROVE", "BLOCK"):
        raise HTTPException(400, "decision must be APPROVE or BLOCK")
    with closing(_db()) as conn:
        row = conn.execute("SELECT result FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown review id")
        result = json.loads(row[0]) if row[0] else {}
        result["human_decision"] = {"decision": body.decision, "by": "reviewer"}
        conn.execute("UPDATE reviews SET result=? WHERE id=?", (json.dumps(result), review_id))
        conn.commit()
    return {"id": review_id, "decision": body.decision, "by": "reviewer"}
