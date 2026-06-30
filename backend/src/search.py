"""
Stage 3: Marengo evidence pass.

For every policy we run its configured search probes against the index. Each hit
comes back with a start, end, score and confidence. This is the independent
evidence layer: rather than trusting the Pegasus narrative alone, we corroborate
specific known-bad patterns (product in the eye, a "cures acne" claim, spoken
profanity) with direct, timestamped search hits the reviewer can click and watch.

Two passes that must agree before we act on the most serious calls is the core
trust mechanism of the whole system.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .client import TwelveLabsClient
from .schemas import Confidence, SearchEvidence

_CONF_RANK = {"low": 0, "medium": 1, "high": 2}


def run_search_probes(
    client: TwelveLabsClient,
    video_id: str,
    policies: List[Dict[str, Any]],
    index_id: str,
) -> Dict[str, List[SearchEvidence]]:
    """Return a map of policy_id to its corroborating timestamped evidence.

    Probes search within ``index_id`` scoped to the uploaded ``video_id``.
    """
    evidence: Dict[str, List[SearchEvidence]] = {}
    for policy in policies:
        pid = policy["id"]
        hits: List[SearchEvidence] = []
        for probe in policy.get("probes", []):
            floor = probe.get("confidence_floor", "low")
            results = client.search(
                index_id,
                probe["query"],
                modalities=probe.get("modality", ["visual"]),
                page_limit=5,
                video_id=video_id,
            )
            for r in results:
                conf = str(r.get("confidence", "low")).lower()
                if _CONF_RANK.get(conf, 0) < _CONF_RANK.get(floor, 0):
                    continue  # below the probe's confidence floor, ignore
                hits.append(
                    SearchEvidence(
                        policy_id=pid,
                        query=probe["query"],
                        start=float(r.get("start", 0.0)),
                        end=float(r.get("end", 0.0)),
                        score=float(r.get("score", 0.0)),
                        confidence=Confidence(conf),
                    )
                )
        if hits:
            evidence[pid] = hits
    return evidence
