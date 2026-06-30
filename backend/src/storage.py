"""
Supabase Storage for uploaded videos.

When configured (SUPABASE_URL + SUPABASE_SERVICE_KEY + SUPABASE_BUCKET), an
uploaded creative is pushed to the bucket and a time-limited signed URL is
returned. The pipeline hands that URL to TwelveLabs, which fetches the video
directly — so the bytes live in your storage, not on local disk, and the
app server never has to stream them onward.

Not configured -> enabled() is False and the API keeps files on local disk.
This is the "Supabase as input + storage" path: one system for upload, storage
and database, with no Google Drive / OAuth.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
BUCKET = os.environ.get("SUPABASE_BUCKET", "Clearframe")


def enabled() -> bool:
    return bool(SUPABASE_URL and SERVICE_KEY and BUCKET)


def upload_and_sign(local_path: str, dest_path: str, expires: int = 7 * 24 * 3600) -> str:
    """Upload a local file to the bucket at dest_path; return a signed download URL."""
    base = f"{SUPABASE_URL}/storage/v1"
    auth = {"Authorization": f"Bearer {SERVICE_KEY}", "apikey": SERVICE_KEY}
    path = quote(dest_path, safe="/")
    body = Path(local_path).read_bytes()

    up = httpx.post(
        f"{base}/object/{BUCKET}/{path}",
        headers={**auth, "Content-Type": "video/mp4", "x-upsert": "true"},
        content=body, timeout=httpx.Timeout(300.0, connect=10.0),
    )
    if up.status_code >= 400:
        raise RuntimeError(f"Storage upload failed: {up.status_code} {up.text[:200]}")

    sign = httpx.post(
        f"{base}/object/sign/{BUCKET}/{path}",
        headers={**auth, "Content-Type": "application/json"},
        json={"expiresIn": expires}, timeout=30,
    )
    if sign.status_code >= 400:
        raise RuntimeError(f"Sign failed: {sign.status_code} {sign.text[:200]}")
    signed = sign.json()["signedURL"]
    return f"{base}{signed}" if signed.startswith("/") else f"{base}/{signed}"
