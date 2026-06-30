"""
Per-campaign bucket sync.

A campaign can be linked to a source folder — a local directory or a Supabase
Storage prefix. New video files dropped there are picked up by the background
scheduler (see api.py) and ingested as reviews automatically, so a creator can
just drop files in a watched folder instead of using the upload UI.

Dedup is by *source key* (a stable identifier for where the file came from), so
the same object is never ingested twice even across restarts.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from src import db, storage
from src.precheck import VIDEO_EXTS

UPLOADS = Path(__file__).resolve().parent.parent / "uploads"


def _parse(ref: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a bucket reference into (kind, location).

      ""                      -> (None, None)        no bucket configured
      supabase://<prefix>     -> ("supabase", prefix)
      file://<path>           -> ("local", path)
      <bare path>             -> ("local", path)     a bare path is a local folder
    """
    ref = (ref or "").strip()
    if not ref:
        return None, None
    if ref.startswith("supabase://"):
        return "supabase", ref[len("supabase://"):].strip("/")
    if ref.startswith("file://"):
        return "local", ref[len("file://"):]
    return "local", ref


def list_new(campaign: dict) -> List[Tuple[str, str]]:
    """Return [(source_key, local_path)] for files not yet ingested for this
    campaign. Downloads remote objects to backend/uploads as needed."""
    bucket = ((campaign.get("config") or {}).get("bucket"))
    kind, loc = _parse(bucket or "")
    if not kind:
        return []

    out: List[Tuple[str, str]] = []

    if kind == "local":
        folder = Path(loc)
        if not folder.is_dir():
            return []
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.suffix.lower() not in VIDEO_EXTS:
                continue
            abspath = str(f.resolve())
            source_key = f"local://{abspath}"
            if db.source_exists(source_key):
                continue
            out.append((source_key, abspath))
        return out

    if kind == "supabase":
        if not storage.enabled():
            return []
        prefix = loc
        for name in storage.list_objects(prefix):
            source_key = f"supabase://{prefix}/{name}"
            if db.source_exists(source_key):
                continue
            dest = UPLOADS / f"sync_{db.new_id('f')}_{name}"
            try:
                storage.download(f"{prefix}/{name}", str(dest))
            except Exception:
                continue
            out.append((source_key, str(dest)))
        return out

    return []
