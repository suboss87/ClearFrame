"""
Seed a clean demo state: ONE campaign with four sample creatives covering every
verdict (APPROVE / REVIEW / BLOCK), computed from the recorded fixtures so the
result is the canonical, deterministic demo — no API key or real videos needed.

Run:  python seed_demo.py        (or `make seed` from the repo root)

Safe to re-run: it wipes campaigns + reviews and reseeds. Uploaded videos in
uploads/ and your saved API key are untouched.
"""

from __future__ import annotations

from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from src import db
from src.client import TwelveLabsClient
from src.pipeline import load_config, review_video

CAMPAIGN = (
    "Ora Velvet Matte",
    "Spring 2026 launch: creator videos featuring the Ora Velvet Matte "
    "matte lipstick & foundation: tutorials, product demos, and GRWM routines.",
)
SCENARIOS = ["clean_tutorial", "eye_misuse_claim", "mild_profanity", "offbrief_clickbait"]


def run() -> None:
    db.init()
    db.execute("DELETE FROM reviews")
    db.execute("DELETE FROM campaigns")
    db.init()  # recreate the Unsorted inbox
    camp = db.create_campaign(*CAMPAIGN)
    cfg = load_config()
    client = TwelveLabsClient(mock=True)  # always fixtures, regardless of stored key
    print(f"Seeding '{camp['name']}':")
    for s in SCENARIOS:
        rid = db.create_review(camp["id"], f"{s}.mp4")
        result, video_id = review_video(client, "mock-index", f"{s}.mp4", cfg)
        payload = result.model_dump(mode="json")
        payload["campaign_id"] = camp["id"]
        db.finish_review(rid, "done", payload, video_id=video_id)
        print(f"  {s}.mp4  ->  {result.decision.value}")
    print(f"Done. 1 campaign, {len(SCENARIOS)} creatives. Unsorted inbox kept empty.")


if __name__ == "__main__":
    run()
