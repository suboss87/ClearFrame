#!/usr/bin/env python3
"""
Perception smoke test: score the pipeline's REAL stored results against
independently-known ground truth (perception_truth.yaml).

The engine eval (run_eval.py) proves the decision layer holding perception
fixed. This script measures the other half - did Pegasus actually catch what
is known to be in each demo video, and how far off are the evidence windows:

  * verdict accuracy against the expected verdict
  * per-violation catch / miss, plus false flags (policies flagged that the
    truth says are clean)
  * timestamp accuracy, for violations with a verified truth window: whether
    the evidence window overlaps it, and the gap in seconds when it does not

Reads results from the running API (default http://localhost:8000) so it works
against whichever database the backend is on. Read-only; changes nothing.

HONEST SCOPE: with a handful of videos this is a regression smoke test, not a
statistical benchmark, and the output says so. Its value is direction, not
precision: change a prompt or upgrade the model, re-run the batch, re-run
this, and see whether catch rate or timestamp error moved.

Usage:
    python eval/perception_eval.py
    python eval/perception_eval.py --api http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import yaml

TRUTH = Path(__file__).resolve().parent / "perception_truth.yaml"


def fetch_reviews(api: str) -> list:
    with urllib.request.urlopen(f"{api}/api/reviews", timeout=15) as r:
        return json.loads(r.read())


def overlap_or_gap(ev_start: float, ev_end: float, lo: float, hi: float) -> float:
    """0.0 when the evidence window overlaps the truth window, else the gap in
    seconds between them (how far the reviewer would have to scrub)."""
    if ev_end >= lo and ev_start <= hi:
        return 0.0
    return lo - ev_end if ev_end < lo else ev_start - hi


def run(api: str) -> int:
    truth = yaml.safe_load(TRUTH.read_text())["videos"]
    reviews = {r["file"]: r for r in fetch_reviews(api) if r.get("status") == "done"}

    verdict_hits = 0
    catches, misses, false_flags = [], [], []
    window_hits, window_gaps = 0, []
    scored, skipped = 0, []

    for case in truth:
        r = reviews.get(case["file"])
        if not r or not r.get("result"):
            skipped.append(case["file"])
            continue
        scored += 1
        res = r["result"]
        expected = case["expect_verdict"]
        got = res.get("decision")
        v_ok = got == expected
        verdict_hits += v_ok
        print(f"\n{case['file']}  verdict: {got} (expected {expected}) {'OK' if v_ok else 'WRONG'}")

        flagged = {p["policy_id"]: p for p in res.get("policy_verdicts", []) if p.get("triggered")}
        truth_policies = {v["policy"] for v in case.get("violations") or []}

        for v in case.get("violations") or []:
            pv = flagged.get(v["policy"])
            if not pv:
                misses.append((case["file"], v["policy"]))
                print(f"  MISS   {v['policy']}: {v['what']}")
                continue
            catches.append((case["file"], v["policy"]))
            line = f"  CAUGHT {v['policy']}: {v['what']}"
            if v.get("window"):
                lo, hi = v["window"]
                ev = pv.get("evidence") or []
                if ev:
                    gap = min(overlap_or_gap(e["start"], e["end"], lo, hi) for e in ev)
                    window_gaps.append(gap)
                    if gap == 0.0:
                        window_hits += 1
                        line += f"  [window OK: evidence overlaps {lo}-{hi}s]"
                    else:
                        line += f"  [window OFF by {gap:.1f}s vs truth {lo}-{hi}s]"
                else:
                    line += "  [no evidence window to score]"
            print(line)

        for pid in flagged.keys() - truth_policies:
            false_flags.append((case["file"], pid))
            print(f"  FALSE FLAG {pid}: flagged, but truth says clean")

    total_viol = len(catches) + len(misses)
    print("\n" + "=" * 70)
    print(f"Videos scored: {scored}/{len(truth)}"
          + (f"   (missing from queue: {', '.join(skipped)})" if skipped else ""))
    print(f"Verdicts:      {verdict_hits}/{scored} correct")
    if total_viol:
        print(f"Violations:    {len(catches)}/{total_viol} caught, {len(false_flags)} false flag(s)")
    if window_gaps:
        mean_gap = sum(window_gaps) / len(window_gaps)
        print(f"Timestamps:    {window_hits}/{len(window_gaps)} evidence windows overlap the "
              f"verified truth window; mean miss distance {mean_gap:.1f}s")
    print("\nNOTE: smoke test over a handful of scripted videos - a regression signal,")
    print("not a statistical benchmark. Grow perception_truth.yaml to strengthen it.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    sys.exit(run(ap.parse_args().api))
