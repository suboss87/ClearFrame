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

import os
import shutil
import threading
import time
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

from src import bucket_sync, db, keystore, storage
from src.precheck import precheck
from src.client import TwelveLabsClient, TwelveLabsError
from src.indexes import ensure_index
from src.pipeline import load_config, review_video

UPLOADS = Path(__file__).resolve().parent / "uploads"
UPLOADS.mkdir(exist_ok=True)

app = FastAPI(title="Clearframe API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db.init()
_cfg = load_config()

# No durable job queue backs review processing (see _run_pipeline below), so any
# review still "queued" or "processing" at startup was orphaned by a previous
# process that died mid-flight - fail it now instead of leaving the reviewer
# console showing a spinner nothing is actually driving.
_orphaned = db.fail_orphaned_reviews()
if _orphaned:
    print(f"[startup] failed {len(_orphaned)} orphaned review(s) from a previous run: {_orphaned}")

# How often (seconds) the background scheduler scans linked buckets for new files.
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "30"))
_SYNC_LOCK = threading.Lock()  # one bucket sweep at a time (daemon + manual /api/sync)


def _sync_once() -> int:
    """Scan every campaign with a linked bucket and ingest any new files, running
    each through the full pipeline. Returns the count ingested, or -1 if a sweep is
    already running. The lock stops the daemon and a manual /api/sync (or two ticks)
    from double-ingesting the same file and paying TwelveLabs twice."""
    if not _SYNC_LOCK.acquire(blocking=False):
        return -1
    try:
        count = 0
        # When several campaigns link the SAME bucket, only the newest one
        # ingests new files - old campaigns keep their existing reviews but
        # stop pulling in whatever gets dropped later. list_campaigns() is
        # ordered newest-first, so the first campaign seen per bucket wins.
        claimed_buckets = set()
        for c in db.list_campaigns():
            bucket_ref = (c.get("config") or {}).get("bucket")
            if not bucket_ref:
                continue
            if bucket_ref in claimed_buckets:
                continue
            claimed_buckets.add(bucket_ref)
            try:
                # Two passes on purpose. First: create every review row and
                # stage every file, so the whole batch appears in the queue
                # as "queued" within one UI poll. Then: process them. With
                # the old single pass, video 2 didn't even get a row until
                # video 1's full pipeline (a minute or more of TwelveLabs
                # work) had finished, so most of a fresh batch was invisible
                # for minutes.
                pending = []
                for src, path, display in bucket_sync.list_new(c):
                    rid = db.create_review(c["id"], display, source=src)
                    # Ledger entry survives review deletion, so removing a
                    # creative in the UI never causes the sweep to re-ingest it.
                    db.mark_ingested(c["id"], src)
                    # Stage the file as uploads/{rid}_{display} so it shows a clean
                    # name and the player (which globs {review_id}_*) can serve it.
                    target = UPLOADS / f"{rid}_{display}"
                    try:
                        p = Path(path)
                        if p.parent.resolve() == UPLOADS.resolve():
                            p.rename(target)            # our downloaded temp: move
                        else:
                            shutil.copy2(p, target)     # user's local file: leave source intact
                        path = str(target)
                    except Exception as exc:
                        print(f"[sync] staging {display} failed: {exc}")
                    pending.append((rid, path))
                for rid, path in pending:
                    _run_pipeline(rid, path, c["id"])
                    count += 1
            except Exception as exc:
                print(f"[sync] campaign {c.get('id')} failed: {exc}")
        return count
    finally:
        _SYNC_LOCK.release()


def _sync_loop() -> None:
    while True:
        try:
            _sync_once()
        except Exception:
            pass
        time.sleep(SYNC_INTERVAL)


# Start the background scheduler unless explicitly disabled (e.g. in tests).
if os.environ.get("SYNC_ENABLED", "1") != "0":
    threading.Thread(target=_sync_loop, daemon=True).start()


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
    bucket: Optional[str] = None                      # linked source folder / supabase:// prefix


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
    if body.bucket is not None:
        cfg["bucket"] = body.bucket.strip()
    return cfg


@app.post("/api/campaigns")
def create_campaign(body: CampaignBody):
    campaign = db.create_campaign(body.name.strip(), body.brief.strip(), _campaign_config(body))
    # A campaign linked to a bucket should start ingesting immediately, not
    # sit dark until the next scheduled sweep (up to SYNC_INTERVAL away).
    if (campaign.get("config") or {}).get("bucket"):
        threading.Thread(target=_sync_once, daemon=True).start()
    return campaign


@app.put("/api/campaigns/{cid}")
def update_campaign(cid: str, body: CampaignBody):
    if cid == "cmp_unsorted":
        raise HTTPException(400, "The default Unsorted campaign can't be edited")
    existing = db.get_campaign(cid)
    if not existing:
        raise HTTPException(404, "Unknown campaign")
    # Merge over the existing config so a partial edit (say, just the master
    # prompt) never silently wipes the rest of the campaign's settings.
    cfg = {**(existing.get("config") or {}), **_campaign_config(body)}
    campaign = db.update_campaign(cid, body.name.strip(), body.brief.strip(), cfg)
    # The bucket link may have just been added or changed; ingest right away.
    if cfg.get("bucket"):
        threading.Thread(target=_sync_once, daemon=True).start()
    return campaign


@app.get("/api/storage/folders")
def storage_folders(prefix: str = ""):
    """Folders in the Supabase bucket — powers the campaign 'linked bucket' picker
    so the team selects where creators upload instead of typing a path."""
    if not storage.enabled():
        return {"enabled": False, "bucket": None, "folders": []}
    return {"enabled": True, "bucket": storage.BUCKET, "folders": storage.list_folders(prefix)}


@app.post("/api/sync")
def sync():
    """Trigger a bucket sweep in the background (also runs on a schedule). Returns
    immediately so a long sweep never blocks the request or a worker thread."""
    threading.Thread(target=_sync_once, daemon=True).start()
    return {"started": True}


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


@app.delete("/api/campaigns/{cid}")
def delete_campaign(cid: str):
    if cid == "cmp_unsorted":
        raise HTTPException(400, "The default Unsorted campaign can't be deleted")
    if not db.get_campaign(cid):
        raise HTTPException(404, "Unknown campaign")
    db.delete_campaign(cid)
    return {"id": cid, "deleted": True}


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


def _reject_review(review_id: str, reason: str, campaign_id: str) -> None:
    """Finish a review as BLOCK with no model spend — used by the pre-check gate."""
    db.finish_review(review_id, "done", {
        "decision": "BLOCK", "confidence": "high", "description": "",
        "on_brief": False, "relevance_score": 0.0,
        "reasons": [f"Rejected before analysis: {reason}"],
        "policy_verdicts": [], "human_review_required": False,
        "campaign_id": campaign_id, "precheck_rejected": True})


def _run_pipeline(review_id: str, file_path: str, campaign_id: str) -> None:
    """Worker: run the creative through the pipeline, streaming stage progress
    into the DB. In production this is a queue consumer resumed by a webhook."""
    client = get_client()
    try:
        # The campaign (or the review itself, via cascade) can be deleted
        # between ingestion and this worker starting, e.g. a user deletes a
        # campaign while a bucket sweep for it is mid-batch. Bail out BEFORE
        # any TwelveLabs spend rather than analysing a creative nobody can see.
        campaign = db.get_campaign(campaign_id)
        if campaign is None or db.get_review(review_id) is None:
            db.delete_review(review_id)  # no-op if the cascade already removed it
            print(f"[pipeline] skipped {review_id}: campaign {campaign_id} deleted before processing")
            return
        # Pre-check applies to LOCAL files only. URL inputs (a Supabase signed URL
        # from upload(), or a public/Drive link from from_url()) are pre-checked
        # before upload, or left to TwelveLabs to reject on fetch — running the
        # filesystem pre-check on a URL would wrongly reject every one.
        duration_s = None
        if not str(file_path).startswith(("http://", "https://")):
            ok, reason, meta = precheck(file_path, is_duplicate=lambda h: db.hash_exists(h, campaign_id, exclude_review=review_id))
            if meta.get("content_hash"):
                db.set_content_hash(review_id, meta["content_hash"])
            if not ok:
                _reject_review(review_id, reason, campaign_id)
                return
            # ffprobe already measured the clip; feeding the duration into the
            # analysis prompt keeps Pegasus timestamps inside the real runway.
            duration_s = meta.get("duration")
        index_id = ensure_index(client)
        cfg, brief, guidance = _effective_cfg(campaign)
        result, video_id = review_video(
            client, index_id, file_path, cfg,
            on_stage=lambda i: db.set_review_stage(review_id, i),
            brief_override=brief,
            guidance=guidance,
            duration_s=duration_s,
        )
        payload = result.model_dump(mode="json")
        payload["campaign_id"] = campaign_id
        db.finish_review(review_id, "done", payload, video_id=video_id)
        # Blocking is automatic, so is telling the creator. No reviewer step.
        if result.decision.value == "BLOCK":
            db.add_audit(review_id, "System", "NOTIFY", "Creator notified automatically, ad blocked.")
    except Exception as exc:  # surface failures, never swallow
        db.finish_review(review_id, "failed", {"error": str(exc), "campaign_id": campaign_id})
        # A synced file that failed (network blip, malformed model response,
        # etc.) should be retried by the next sweep, not silently blacklisted
        # forever just because it was already recorded as ingested.
        r = db.get_review(review_id)
        if r and r.get("source"):
            db.unmark_ingested(campaign_id, r["source"])


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
        # Pre-check the LOCAL file before paying to upload it to Storage + index it.
        ok, reason, meta = precheck(str(dest), is_duplicate=lambda h: db.hash_exists(h, campaign_id, exclude_review=rid))
        if meta.get("content_hash"):
            db.set_content_hash(rid, meta["content_hash"])
        if not ok:
            _reject_review(rid, reason, campaign_id)
            try:
                dest.unlink()
            except Exception:
                pass
            created.append({"id": rid, "file": f.filename, "status": "done"})
            continue
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


@app.delete("/api/reviews/{review_id}")
def delete_review(review_id: str):
    r = db.get_review(review_id)
    if not r:
        raise HTTPException(404, "Unknown review id")
    # Remove the staged local copy too, otherwise every deleted review leaks
    # its video file in backend/uploads/ forever.
    for f in UPLOADS.glob(f"{review_id}_*"):
        try:
            f.unlink()
        except OSError:
            pass
    db.delete_review(review_id)
    return {"id": review_id, "deleted": True}


@app.post("/api/reviews/{review_id}/decision")
def decide(review_id: str, body: DecisionBody):
    if body.decision not in ("APPROVE", "BLOCK"):
        raise HTTPException(400, "decision must be APPROVE or BLOCK")
    if not db.get_review(review_id):
        raise HTTPException(404, "Unknown review id")
    db.set_human_decision(review_id, body.decision)
    db.add_audit(review_id, REVIEWER_NAME, body.decision, body.comment)
    # A human override to BLOCK also notifies the creator automatically.
    if body.decision == "BLOCK":
        db.add_audit(review_id, "System", "NOTIFY", "Creator notified automatically, ad blocked.")
    return {"id": review_id, "decision": body.decision, "by": REVIEWER_NAME}


@app.post("/api/reviews/{review_id}/undo")
def undo_decision(review_id: str):
    """Reverse a human override, reverting the review to the automated verdict.
    The audit trail is append-only — this logs the reversal rather than erasing
    the fact that an override happened."""
    if not db.get_review(review_id):
        raise HTTPException(404, "Unknown review id")
    db.set_human_decision(review_id, None)
    db.add_audit(review_id, REVIEWER_NAME, "UNDO", "Reverted the override back to the automated verdict.")
    return {"id": review_id, "undone": True}


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
            lines.append(f"  - {p.get('label')} [{p.get('severity')}]" + (f": {ev}" if ev else ""))
    return "\n".join(lines)


@app.post("/api/reviews/{review_id}/ask")
def ask(review_id: str, body: AskBody):
    """Chat copilot: answers from the video (Pegasus), ClearFrame's analysis,
    AND the Marengo index - the reviewer's question is searched against this
    video's index so the copilot can ground its answer in measured moments
    (clip start/end times Marengo indexed), not only in what Pegasus recalls."""
    r = db.get_review(review_id)
    if not r:
        raise HTTPException(404, "Unknown review id")
    video_id = r.get("video_id")
    if not video_id:
        raise HTTPException(409, "Video is not indexed yet")
    client = get_client()
    question = body.question.strip()
    context = _chat_context(_review_public(r).get("result"))
    # Best-effort Marengo grounding: search failures never break the chat.
    if not client.mock and not str(video_id).startswith("mock-"):
        try:
            hits = client.search(keystore.get_index_id(), question,
                                 ["visual", "audio"], page_limit=5, video_id=video_id)
            spans = [f"{float(h['start']):.1f}-{float(h['end']):.1f}s"
                     for h in hits if h.get("start") is not None][:5]
            if spans:
                context += ("\nMarengo index search for this question matched these "
                            "moments (measured clip times): " + ", ".join(spans))
        except Exception:
            pass
    answer = client.ask(video_id, question, context)
    return {"answer": answer}
