"""
Stage 1: on-brief relevance gate.

We do the cheap filter first. Before spending a full compliance pass on a video,
we ask: is this even an ad for the campaign product? Off-brief clickbait that
barely shows the product is filtered here. This protects spend and review
bandwidth, which is exactly the kind of efficiency a buyer cares about at scale.

Two signals, combined:
  * a Marengo text-to-video search of the brief's positive signals against the
    creative; the best clip score is the relevance score
  * the Pegasus on_brief boolean from the analysis pass, used as a tie-breaker

We keep them separate so the demo can show that the two methods agree, which is
itself a trust signal.
"""

from __future__ import annotations

from typing import Dict, List

from .client import TwelveLabsClient


def relevance_score(
    client: TwelveLabsClient,
    video_id: str,
    positive_signals: List[str],
    index_id: str,
) -> float:
    """Return the best clip score across the brief's positive signals (0 to 1).

    Searches within ``index_id`` scoped to the uploaded ``video_id``.
    """
    best = 0.0
    for signal in positive_signals:
        hits = client.search(index_id, signal, modalities=["visual"], page_limit=1, video_id=video_id)
        for hit in hits:
            best = max(best, _normalise(hit.get("score", 0.0)))
    return round(best, 3)


def _normalise(score: float) -> float:
    """
    Marengo scores are not 0 to 1 out of the box. We min-max into a 0 to 1 band
    using an empirical ceiling. In production this ceiling is calibrated per
    index from a labelled set, not guessed. Flagged as a tuning point.
    """
    ceiling = 100.0
    return max(0.0, min(1.0, score / ceiling))
