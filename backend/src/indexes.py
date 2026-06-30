"""
TwelveLabs index lifecycle.

Videos are uploaded into an index. We create one on demand (the first time a key
is saved / a video is uploaded) and remember its id in settings, so we reuse the
same index across uploads instead of creating one per video.
"""

from __future__ import annotations

from .client import TwelveLabsClient
from . import keystore


def ensure_index(client: TwelveLabsClient) -> str:
    """Return the working index id. A mock index id is never reused once a real
    key is in play. In real mode we REUSE an existing 'clearframe-index' if the
    account already has one (creating a duplicate name is a 400), else create it."""
    idx = keystore.get_index_id()
    if idx and not (idx == "mock-index" and not client.mock):
        return idx
    idx = client.find_index("clearframe-index") or client.create_index("clearframe-index")
    keystore.set_index_id(idx)
    return idx
