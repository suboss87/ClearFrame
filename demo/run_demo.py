"""
Greenlight demo runner.

Runs the full pipeline over a set of sample creator videos and prints a decision
with timestamped evidence for each. Runs in mock mode out of the box (no API key
needed), so it is safe to run live in front of a panel.

Usage:
    python -m demo.run_demo            # mock mode, all four scenarios
    python -m demo.run_demo --html     # also write demo/report.html

With a real key set TL_API_KEY and pass --live plus real video paths.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.client import TwelveLabsClient
from src.pipeline import load_config, review_video
from src.schemas import Decision, GreenlightResult

SCENARIOS = [
    ("clean_tutorial.mp4", "Clean product tutorial"),
    ("eye_misuse_claim.mp4", "Unsafe eye-area use plus a medical claim"),
    ("mild_profanity.mp4", "On-brief but one mild swear word"),
    ("offbrief_clickbait.mp4", "Off-brief lifestyle clickbait"),
]

_BADGE = {Decision.approve: "APPROVE  ", Decision.review: "REVIEW   ", Decision.block: "BLOCK    "}
_COLOR = {Decision.approve: "\033[92m", Decision.review: "\033[93m", Decision.block: "\033[91m"}
_RESET = "\033[0m"


def print_result(label: str, r: GreenlightResult) -> None:
    color = _COLOR[r.decision]
    print("\n" + "=" * 78)
    print(f"{color}{_BADGE[r.decision]}{_RESET} {r.video_ref}   ({label})")
    print(f"  confidence: {r.confidence.value}   on-brief: {r.on_brief}   "
          f"relevance: {r.relevance_score:.2f}   human review: {r.human_review_required}")
    print(f"  description: {r.description}")
    print("  why:")
    for reason in r.reasons:
        print(f"    - {reason}")
    triggered = [v for v in r.policy_verdicts if v.triggered]
    if triggered:
        print("  timestamped evidence:")
        for v in triggered:
            for e in v.evidence:
                print(f"    - [{v.policy_id}] {e.start:.1f}s to {e.end:.1f}s "
                      f"(conf {e.confidence.value}): {e.query}")
            if not v.evidence:
                print(f"    - [{v.policy_id}] flagged by model reasoning (no search corroboration)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true", help="write an HTML evidence report")
    args = ap.parse_args()

    client = TwelveLabsClient()  # mock by default when no TL_API_KEY
    cfg = load_config()
    index_id = "greenlight-demo-index"

    mode = "MOCK (fixtures)" if client.mock else "LIVE (TwelveLabs API)"
    print(f"Greenlight ad compliance gate  |  mode: {mode}")
    print(f"Advertiser: {cfg['policies']['advertiser']}  |  Campaign: {cfg['policies']['campaign']}")

    results = []
    for filename, label in SCENARIOS:
        r = review_video(client, index_id, filename, cfg)
        results.append((label, r))
        print_result(label, r)

    # Summary line.
    counts = {Decision.approve: 0, Decision.review: 0, Decision.block: 0}
    for _, r in results:
        counts[r.decision] += 1
    print("\n" + "=" * 78)
    print(f"SUMMARY  approve={counts[Decision.approve]}  "
          f"review={counts[Decision.review]}  block={counts[Decision.block]}")

    if args.html:
        from demo.report import write_report
        out = write_report(cfg, results)
        print(f"\nHTML report written to {out}")


if __name__ == "__main__":
    main()
