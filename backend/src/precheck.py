"""
Deterministic pre-check gate — runs before any TwelveLabs call.

A creative is screened against cheap, local, deterministic rules first: is it a
real video file, the right size, a sane duration, and not a duplicate of one we
already analysed. Anything that fails here never reaches TwelveLabs — it surfaces
as a BLOCK with a plain-English reason, reusing the same UI as a real verdict.

The point is to spend zero model budget on junk: empty files, screenshots
renamed to .mp4, 90-minute exports, or the same clip submitted twice.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
MIN_BYTES = 10 * 1024            # 10 KB — below this it cannot be a real video
MAX_BYTES = 1024 ** 3           # 1 GB
MIN_SECONDS = 2.0
MAX_SECONDS = 20 * 60           # 20 minutes


def file_hash(path: str) -> str:
    """sha256 of the file, streamed in 1 MB chunks (cheap content fingerprint)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ffprobe_duration(path: str) -> Optional[float]:
    """Return the video duration in seconds via ffprobe, or None if it cannot be
    read (ffprobe missing, non-zero exit, or no duration field)."""
    if not shutil.which("ffprobe"):
        return None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        dur = json.loads(proc.stdout).get("format", {}).get("duration")
        return float(dur) if dur is not None else None
    except Exception:
        return None


def precheck(path: str, is_duplicate: Optional[Callable[[str], bool]] = None) -> Tuple[bool, str, dict]:
    """Screen a file before analysis.

    Returns (ok, reason, meta). meta always carries content_hash and bytes, plus
    duration when ffprobe can read it. On the first failing rule, returns
    (False, <human reason>, meta); if everything passes, (True, "ok", meta).
    """
    meta: dict = {}
    p = Path(path)

    if not p.is_file():
        return False, "File is missing or is not a file.", meta

    size = p.stat().st_size
    meta["bytes"] = size
    meta["content_hash"] = file_hash(path)

    if size < MIN_BYTES:
        return False, "File is empty or too small to be a video.", meta
    if size > MAX_BYTES:
        return False, "File exceeds the 1 GB limit.", meta

    ext = p.suffix.lower()
    if ext not in VIDEO_EXTS:
        return False, f"Unsupported file type ({ext}).", meta

    # ffprobe is the real "is this a video" test. When it is unavailable we skip
    # duration checks gracefully; when it is present but cannot read a duration,
    # the file is not a real/playable video.
    if shutil.which("ffprobe"):
        duration = _ffprobe_duration(path)
        if duration is None:
            return False, "File is not a readable video.", meta
        meta["duration"] = duration
        if duration < MIN_SECONDS:
            return False, f"Too short ({duration:.1f}s) to be an ad.", meta
        if duration > MAX_SECONDS:
            return False, f"Too long ({duration / 60:.1f} min) for review.", meta

    if is_duplicate is not None and is_duplicate(meta["content_hash"]):
        return False, "Duplicate of a video already submitted.", meta

    return True, "ok", meta
