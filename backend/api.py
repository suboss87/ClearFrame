"""
Clearframe API — the live surface over the compliance pipeline.

What it adds over the pure pipeline:
  * transport + persistence (SQLite via src/db.py)
  * campaigns (group creatives under a brief)
  * live stage progress streamed to the reviewer (poll GET /api/reviews/{id})
  * chat-with-video (POST /api/reviews/{id}/ask -> TwelveLabs Pegasus)
  * human-in-the-loop decisions, recorded alongside the automated verdict
  * secure API-key management: the TwelveLabs key is encrypted at rest and only
    ever used server-side; the browser sees a masked preview, never the key.

Mock by default: with no key saved, the pipeline runs on fixtures so the whole
app works end to end. Save a real key in the UI and the same endpoints hit
TwelveLabs for real.

Run:  uvicorn api:app --reload      # http://localhost:8000
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

# Load backend/.env before anything reads os.environ (db.py picks its backend at
# import time from DATABASE_URL), so credentials apply with zero manual exporting.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src import db, keystore, storage
from src.client import TwelveLabsClient, TwelveLabsError
from src.indexes import ensure_index
from src.pipeline import load_config, review_video

UPLOADS = Path(__file__).resolve().parent / "uploads"
UPLOADS.mkdir(exist_ok=True)

app = FastAPI(title="Clearframe API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db.init()
_cfg = load_config()


def get_client() -> TwelveLabsClient:
    """A client bound to the stored key (mock when none is set)."""
    return TwelveLabsClient(api_key=keystore.get_key())


# ============================================================ health / settings
@app.get("/api/health")
def health():
    return {"ok": True, "mock": not keystore.is_connected(), "db": db.backend_name(),
            "storage": "supabase" if storage.enabled() else "local"}


@app.get("/api/settings")
def settings():
    return {
        "twelvelabs_connected": keystore.is_connected(),
        "masked_key": keystore.masked(),
        "index_id": keystore.get_index_id(),
        "mock": not keystore.is_connected(),
    }


class KeyBody(BaseModel):
    api_key: str


@app.post("/api/settings/twelvelabs-key")
def save_key(body: KeyBody):
    """Encrypt + store the key, then validate it by ensuring an index exists.
    Creating/reading the index is a real authenticated call, so a bad key fails
    here and we roll back rather than persisting a dead credential."""
    key = body.api_key.strip()
    if not key:
        raise HTTPException(400, "Empty API key")
    keystore.save_key(key)
    try:
        client = get_client()
        client.validate()       # real authenticated check; bad key -> raises
        ensure_index(client)    # provision a real index (skips the mock one)
    except Exception as exc:
        keystore.clear_key()
        raise HTTPException(400, f"Key rejected by TwelveLabs: {exc}")
    return settings()


@app.delete("/api/settings/twelvelabs-key")
def delete_key():
    keystore.clear_key()
    return settings()


# ==================================================================== campaigns
class CampaignBody(BaseModel):
    name: str
    brief: str = ""
    relevance_threshold: Optional[float] = None
    auto_min_confidence: Optional[str] = None        # low | medium | high
    profanity_tolerance: Optional[str] = None        # none | limited | lenient
    policies: Optional[dict] = None                  # { "<policy_id>": {"enabled": bool} }
    custom_guidance: Optional[str] = None


def _tally(reviews):
    t = {"APPROVE": 0, "REVIEW": 0, "BLOCK": 0}
    for r in reviews:
        v = (r.get("result") or {}).get("decision") if isinstance(r.get("result"), dict) else None
        if v in t:
            t[v] += 1
    return t


# Config defaults — mirror the global policies.yaml fallbacks. Per-campaign
# config is stored sparse; missing keys fall back to these at pipeline time.
CONFIG_DEFAULTS = {
    "brief": "",
    "relevance_threshold": 0.55,
    "auto_min_confidence": "medium",
    "profanity_tolerance": "limited",
    "policies": {},          # { "<policy_id>": {"enabled": bool} }; absent => enabled
    "custom_guidance": "",
}

# How each profanity tolerance maps onto the profanity policy thresholds.
_PROFANITY_THRESHOLDS = {
    "none": {"block_at": "medium", "review_at": "low"},
    "limited": {"block_at": "high", "review_at": "low"},
    "lenient": {"block_at": "high", "review_at": "medium"},
}


def _campaign_config(body: CampaignBody) -> dict:
    """Build the sparse config dict to persist from a campaign request body.
    Only non-None fields are stored, so omitted fields inherit the defaults."""
    cfg: dict = {}
    if body.brief.strip():
        cfg["brief"] = body.brief.strip()
    if body.relevance_threshold is not None:
        cfg["relevance_threshold"] = body.relevance_threshold
    if body.auto_min_confidence is not None:
        cfg["auto_min_confidence"] = body.auto_min_confidence
    if body.profanity_tolerance is not None:
        cfg["profanity_tolerance"] = body.profanity_tolerance
    if body.policies is not None:
        cfg["policies"] = body.policies
    if body.custom_guidance is not None:
        cfg["custom_guidance"] = body.custom_guidance.strip()
    return cfg


@app.post("/api/campaigns")
def create_campaign(body: CampaignBody):
    return db.create_campaign(body.name.strip(), body.brief.strip(), _campaign_config(body))


@app.get("/api/campaigns")
def list_campaigns():
    # One pass over all reviews, grouped in memory — avoids an N+1 query storm
    # (a per-campaign round-trip is brutal against a remote Postgres).
    by_c: dict = {}
    for r in (_review_public(r) for r in db.list_reviews()):
        by_c.setdefault(r["campaign_id"], []).append(r)
    out = []
    for c in db.list_campaigns():
        rs = by_c.get(c["id"], [])
        out.append({**c, "count": len(rs), "tally": _tally(rs)})
    return out


@app.get("/api/campaigns/{cid}")
def get_campaign(cid: str):
    c = db.get_campaign(cid)
    if not c:
        raise HTTPException(404, "Unknown campaign")
    return {**c, "reviews": [_review_public(r) for r in db.list_reviews(cid)]}


# ===================================================================== reviews
def _effective_cfg(campaign: dict) -> tuple[dict, Optional[str], Optional[str]]:
    """Merge a campaign's config over the global policies.yaml, producing the
    cfg dict passed to review_video plus the brief_override and guidance.

    The Unsorted inbox (cmp_unsorted) and campaigns with no config fall back to
    the global defaults — the returned cfg is the unmodified global config.
    Returns (cfg, brief_override, guidance).
    """
    import copy

    cid = campaign.get("id")
    cc = campaign.get("config") or {}
    if cid == "cmp_unsorted" or not cc:
        return _cfg, None, None

    def _get(key):
        return cc.get(key, CONFIG_DEFAULTS[key])

    policy_cfg = copy.deepcopy(_cfg["policies"])
    policy_overrides = _get("policies") or {}

    effective_policies = []
    for p in policy_cfg["policies"]:
        ov = policy_overrides.get(p["id"], {})
        if ov.get("enabled") is False:           # explicitly disabled -> drop
            continue
        if p["id"] == "profanity":               # map profanity tolerance
            thresholds = _PROFANITY_THRESHOLDS.get(_get("profanity_tolerance"))
            if thresholds:
                p = {**p, **thresholds}
        effective_policies.append(p)

    policy_cfg["policies"] = effective_policies
    policy_cfg["relevance_threshold"] = _get("relevance_threshold")
    policy_cfg["auto_decision_min_confidence"] = _get("auto_min_confidence")

    cfg = {"policies": policy_cfg, "brief": _cfg["brief"]}
    brief = (cc.get("brief") or "").strip() or None
    guidance = (cc.get("custom_guidance") or "").strip() or None
    return cfg, brief, guidance


def _run_pipeline(review_id: str, file_path: str, campaign_id: str) -> None:
    """Worker: run the creative through the pipeline, streaming stage progress
    into the DB. In production this is a queue consumer resumed by a webhook."""
    client = get_client()
    try:
        index_id = ensure_index(client)
        campaign = db.get_campaign(campaign_id) or {}
        cfg, brief, guidance = _effective_cfg(campaign)
        result, video_id = review_video(
            client, index_id, file_path, cfg,
            on_stage=lambda i: db.set_review_stage(review_id, i),
            brief_override=brief,
            guidance=guidance,
        )
        payload = result.model_dump(mode="json")
        payload["campaign_id"] = campaign_id
        db.finish_review(review_id, "done", payload, video_id=video_id)
    except Exception as exc:  # surface failures, never swallow
        db.finish_review(review_id, "failed", {"error": str(exc), "campaign_id": campaign_id})


import re as _re


def _drive_direct_url(url: str) -> str:
    """Convert a Google Drive share link to a direct-download URL TwelveLabs can
    fetch. Any non-Drive URL passes through unchanged (so any public video URL
    works too)."""
    m = _re.search(r"drive\.google\.com/file/d/([^/]+)", url) or _re.search(r"[?&]id=([^&]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def _name_from_url(url: str) -> str:
    if "drive.google.com" in url:
        return "google-drive-video.mp4"
    tail = url.split("?")[0].rstrip("/").split("/")[-1]
    return tail or "video.mp4"


class UrlBody(BaseModel):
    url: str
    campaign_id: str = "cmp_unsorted"


@app.post("/api/reviews/from-url")
def from_url(body: UrlBody, tasks: BackgroundTasks):
    """Ingest a video by URL — a Google Drive share link or any public video URL.
    TwelveLabs fetches it directly; the file never passes through this server."""
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Provide an http(s) URL (e.g. a Google Drive share link)")
    direct = _drive_direct_url(url)
    rid = db.create_review(body.campaign_id, _name_from_url(url))
    tasks.add_task(_run_pipeline, rid, direct, body.campaign_id)
    return {"id": rid, "file": _name_from_url(url), "status": "queued", "source": "drive" if "drive.google" in url else "url"}


@app.post("/api/reviews/upload")
async def upload(tasks: BackgroundTasks, files: List[UploadFile] = File(...), campaign_id: str = Form("cmp_unsorted")):
    """Bulk (or single) upload into a campaign. Each file becomes its own queued
    review and runs independently; the client polls each for live progress."""
    created = []
    for f in files:
        rid = db.create_review(campaign_id, f.filename)
        dest = UPLOADS / f"{rid}_{Path(f.filename).name}"
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        # Prefer Supabase Storage: upload there and hand the pipeline a signed
        # URL (TwelveLabs fetches from your bucket). Fall back to local disk.
        src = str(dest)
        if storage.enabled():
            try:
                src = storage.upload_and_sign(str(dest), f"{campaign_id}/{rid}_{Path(f.filename).name}")
            except Exception as exc:
                print(f"[storage] falling back to local disk: {exc}")
        tasks.add_task(_run_pipeline, rid, src, campaign_id)
        created.append({"id": rid, "file": f.filename, "status": "queued"})
    return {"submitted": len(created), "reviews": created}


def _review_public(r: dict) -> dict:
    import json as _json
    result = r.get("result")
    if isinstance(result, str):
        try:
            result = _json.loads(result)
        except Exception:
            result = None
    return {
        "id": r["id"], "campaign_id": r.get("campaign_id"), "status": r.get("status"),
        "file": r.get("file"), "stage": r.get("stage"), "stage_label": r.get("stage_label"),
        "video_id": r.get("video_id"), "human_decision": r.get("human_decision"),
        "result": result,
        "verdict": (result or {}).get("decision") if result else None,
        "confidence": (result or {}).get("confidence") if result else None,
    }


@app.get("/api/reviews")
def list_reviews(campaign_id: Optional[str] = None):
    return [_review_public(r) for r in db.list_reviews(campaign_id)]


@app.get("/api/reviews/{review_id}/video")
def review_video_file(review_id: str):
    """Stream the uploaded video for playback in the reviewer (supports range
    requests, so seeking works). Only local-disk uploads have a file here; URL
    ingests and seeded demo creatives have none -> 404, UI shows the placeholder."""
    matches = sorted(UPLOADS.glob(f"{review_id}_*"))
    if not matches:
        raise HTTPException(404, "No local video file for this review")
    return FileResponse(str(matches[0]))


REVIEWER_NAME = "Subash Natarajan"


@app.get("/api/reviews/{review_id}")
def get_review(review_id: str):
    r = db.get_review(review_id)
    if not r:
        raise HTTPException(404, "Unknown review id")
    return {**_review_public(r), "audit": db.list_audit(review_id)}


class DecisionBody(BaseModel):
    decision: str  # APPROVE or BLOCK
    comment: Optional[str] = None


@app.post("/api/reviews/{review_id}/decision")
def decide(review_id: str, body: DecisionBody):
    if body.decision not in ("APPROVE", "BLOCK"):
        raise HTTPException(400, "decision must be APPROVE or BLOCK")
    if not db.get_review(review_id):
        raise HTTPException(404, "Unknown review id")
    db.set_human_decision(review_id, body.decision)
    db.add_audit(review_id, REVIEWER_NAME, body.decision, body.comment)
    return {"id": review_id, "decision": body.decision, "by": REVIEWER_NAME}


class NotifyBody(BaseModel):
    comment: Optional[str] = None


@app.post("/api/reviews/{review_id}/notify")
def notify(review_id: str, body: NotifyBody):
    if not db.get_review(review_id):
        raise HTTPException(404, "Unknown review id")
    db.add_audit(review_id, REVIEWER_NAME, "NOTIFY", body.comment or "Creator notified with reasons")
    return {"ok": True}


class AskBody(BaseModel):
    question: str


def _chat_context(result: Optional[dict]) -> str:
    """Flatten ClearFrame's analysis into prompt context for the chat copilot."""
    if not result:
        return "(no analysis available)"
    lines = [
        f"Verdict: {result.get('decision')} (confidence {result.get('confidence')})",
        f"On-brief: {result.get('on_brief')} (relevance {result.get('relevance_score')})",
        f"Description: {result.get('description', '')}",
    ]
    if result.get("reasons"):
        lines.append("Reasons:")
        lines += [f"  - {x}" for x in result["reasons"]]
    flagged = [p for p in result.get("policy_verdicts", []) if p.get("triggered")]
    if flagged:
        lines.append("Flagged policies:")
        for p in flagged:
            ev = "; ".join(f"{e.get('start')}-{e.get('end')}s {e.get('query', '')}" for e in p.get("evidence", []))
            lines.append(f"  - {p.get('label')} [{p.get('severity')}]" + (f" — {ev}" if ev else ""))
    return "\n".join(lines)


@app.post("/api/reviews/{review_id}/ask")
def ask(review_id: str, body: AskBody):
    """Chat copilot: answers from the video (Pegasus) AND ClearFrame's analysis."""
    r = db.get_review(review_id)
    if not r:
        raise HTTPException(404, "Unknown review id")
    video_id = r.get("video_id")
    if not video_id:
        raise HTTPException(409, "Video is not indexed yet")
    context = _chat_context(_review_public(r).get("result"))
    answer = get_client().ask(video_id, body.question.strip(), context)
    return {"answer": answer}
