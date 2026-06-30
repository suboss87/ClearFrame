"""
Data layer for the Clearframe API.

Two interchangeable backends, chosen by env:
  * DATABASE_URL set  -> PostgreSQL (Supabase) via psycopg2
  * unset             -> local SQLite file (zero-config demo)

The schema and access functions are identical for both; only two dialect
differences are abstracted here — the parameter placeholder (? vs %s) and the
upsert clause. Pointing the app at Supabase is therefore one env var, no code
change. Tables are created with IF NOT EXISTS, so a fresh Supabase project is
provisioned on first run.

  campaigns(id, name, brief, config, created_at)
  reviews(id, campaign_id, status, file, video_id, stage, stage_label,
          result, human_decision, created_at)
  settings(key, value)
  audit(id, review_id, actor, action, comment, ts)
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
IS_PG = bool(DATABASE_URL)
DB = Path(__file__).resolve().parent.parent / "clearframe.db"

# Pipeline stages exposed to the UI (must match the frontend PIPELINE order).
STAGES = ["Indexing", "Relevance gate", "Analyzing", "Gathering evidence", "Deciding"]

if IS_PG:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

_POOL = None


def backend_name() -> str:
    return "postgres (supabase)" if IS_PG else "sqlite"


def _pool():
    # A warm pool of connections to remote Postgres — opening a fresh SSL
    # connection per query against Supabase costs hundreds of ms; reusing them
    # is the single biggest latency win.
    global _POOL
    if _POOL is None:
        kw = {"connect_timeout": 10}
        if "sslmode" not in DATABASE_URL:
            kw["sslmode"] = "require"
        _POOL = psycopg2.pool.ThreadedConnectionPool(1, 8, DATABASE_URL, **kw)
    return _POOL


@contextmanager
def _get_conn():
    if IS_PG:
        pool = _pool()
        conn = pool.getconn()
        try:
            yield conn
        finally:
            pool.putconn(conn)
    else:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()


def _cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if IS_PG else conn.cursor()


def _q(sql: str) -> str:
    return sql.replace("?", "%s") if IS_PG else sql


def execute(sql: str, params: tuple = ()) -> None:
    with _get_conn() as conn:
        _cursor(conn).execute(_q(sql), params)
        conn.commit()


def fetchone(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(_q(sql), params)
        row = cur.fetchone()
        return dict(row) if row else None


def fetchall(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(_q(sql), params)
        return [dict(r) for r in cur.fetchall()]


def init() -> None:
    ts = "double precision" if IS_PG else "real"
    execute(f"CREATE TABLE IF NOT EXISTS campaigns (id text PRIMARY KEY, name text, brief text, config text, created_at {ts})")
    # Idempotent migration for DBs created before the per-campaign config column.
    try:
        execute("ALTER TABLE campaigns ADD COLUMN config text")
    except Exception:
        pass
    execute(
        f"""CREATE TABLE IF NOT EXISTS reviews (
              id text PRIMARY KEY, campaign_id text, status text, file text,
              video_id text, stage integer DEFAULT 0, stage_label text,
              result text, human_decision text, created_at {ts})"""
    )
    execute("CREATE TABLE IF NOT EXISTS settings (key text PRIMARY KEY, value text)")
    execute(
        f"""CREATE TABLE IF NOT EXISTS audit (
              id text PRIMARY KEY, review_id text, actor text, action text,
              comment text, ts {ts})"""
    )
    execute(
        "INSERT INTO campaigns (id, name, brief, created_at) VALUES (?,?,?,?) ON CONFLICT (id) DO NOTHING",
        ("cmp_unsorted", "Unsorted", "Single, ad-hoc creatives not tied to a campaign.", time.time()),
    )


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ----------------------------------------------------------------- settings
def get_setting(key: str) -> Optional[str]:
    row = fetchone("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else None


def set_setting(key: str, value: Optional[str]) -> None:
    if value is None:
        execute("DELETE FROM settings WHERE key=?", (key,))
    else:
        execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


# --------------------------------------------------------------- campaigns
def _with_config(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Parse the stored config JSON into a dict (or {} if null/blank)."""
    if row is None:
        return None
    raw = row.get("config")
    try:
        row["config"] = json.loads(raw) if raw else {}
    except Exception:
        row["config"] = {}
    return row


def create_campaign(name: str, brief: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cid = new_id("cmp")
    config_json = json.dumps(config) if config else None
    execute(
        "INSERT INTO campaigns (id, name, brief, config, created_at) VALUES (?,?,?,?,?)",
        (cid, name, brief, config_json, time.time()),
    )
    return {"id": cid, "name": name, "brief": brief, "config": config or {}}


def list_campaigns() -> List[Dict[str, Any]]:
    return [_with_config(r) for r in fetchall("SELECT * FROM campaigns ORDER BY created_at DESC")]


def get_campaign(cid: str) -> Optional[Dict[str, Any]]:
    return _with_config(fetchone("SELECT * FROM campaigns WHERE id=?", (cid,)))


# ----------------------------------------------------------------- reviews
def create_review(campaign_id: str, file: str) -> str:
    rid = new_id("rv")
    execute(
        "INSERT INTO reviews (id, campaign_id, status, file, stage, created_at) VALUES (?,?,?,?,?,?)",
        (rid, campaign_id, "queued", file, 0, time.time()),
    )
    return rid


def set_review_stage(rid: str, stage: int) -> None:
    label = STAGES[stage] if 0 <= stage < len(STAGES) else None
    execute("UPDATE reviews SET status='processing', stage=?, stage_label=? WHERE id=?", (stage, label, rid))


def finish_review(rid: str, status: str, result: Dict[str, Any], video_id: Optional[str] = None) -> None:
    import json
    execute(
        "UPDATE reviews SET status=?, result=?, video_id=COALESCE(?, video_id), stage=? WHERE id=?",
        (status, json.dumps(result), video_id, len(STAGES), rid),
    )


def set_human_decision(rid: str, decision: str) -> None:
    execute("UPDATE reviews SET human_decision=? WHERE id=?", (decision, rid))


def get_review(rid: str) -> Optional[Dict[str, Any]]:
    return fetchone("SELECT * FROM reviews WHERE id=?", (rid,))


# ------------------------------------------------------------------- audit
def add_audit(review_id: str, actor: str, action: str, comment: Optional[str] = None) -> None:
    execute(
        "INSERT INTO audit (id, review_id, actor, action, comment, ts) VALUES (?,?,?,?,?,?)",
        (new_id("aud"), review_id, actor, action, comment, time.time()),
    )


def list_audit(review_id: str) -> List[Dict[str, Any]]:
    rows = fetchall("SELECT actor, action, comment, ts FROM audit WHERE review_id=? ORDER BY ts ASC", (review_id,))
    return rows


def list_reviews(campaign_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if campaign_id:
        return fetchall("SELECT * FROM reviews WHERE campaign_id=? ORDER BY created_at DESC", (campaign_id,))
    return fetchall("SELECT * FROM reviews ORDER BY created_at DESC")
