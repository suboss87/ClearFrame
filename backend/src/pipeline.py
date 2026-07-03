"""
Pipeline orchestrator.

Wires the stages in order for one video:

  ingest/index  ->  relevance gate  ->  Pegasus reasoning  ->  Marengo evidence
                ->  deterministic decision  ->  ComplianceResult

In production this is one worker pulling from a queue. Indexing is async (submit,
then resume on the index.task.ready webhook). Here we run it inline for clarity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import yaml

from .analyze import run_analysis
from .client import TwelveLabsClient
from .decision import evaluate
from .schemas import ComplianceResult

CONFIG = Path(__file__).resolve().parent.parent / "config"

# Stage indices reported to the UI; match db.STAGES and the frontend PIPELINE.
STAGE_INDEXING, STAGE_RELEVANCE, STAGE_ANALYZING, STAGE_EVIDENCE, STAGE_DECIDING = range(5)

# How far (seconds) a Marengo-measured clip may sit from a Pegasus-estimated
# timestamp and still be trusted as the same moment. Beyond this, the search
# hit is probably a different part of the video and using it would move the
# evidence AWAY from the violation instead of onto it.
SNAP_TOLERANCE_S = 5.0
# A returned clip covering most of the video ("the whole clip matches") carries
# no localization information; only tighter clips are trusted as measurements.
MAX_SPAN_FRACTION = 0.8
MAX_SPAN_S = 15.0


def refine_timestamps(client: TwelveLabsClient, index_id: str, video_id: str, analysis,
                      duration_s: float = None) -> None:
    """Attach Marengo-measured clip boundaries to each finding.

    Pegasus WRITES its timestamps as part of a generated answer - an estimate
    from its sampled view of the video that can run early or late, especially
    when the offending word sits inside a longer sentence. Marengo's index, by
    contrast, returns clip start/end times it MEASURED while indexing. Each
    finding's evidence text is searched against this one video (scoped
    server-side; on a shared index the global top-N for a common word belongs
    to other videos) and matching clips are stored on finding.spans, which the
    decision engine prefers over timestamp padding when building the evidence
    window - so the window is guaranteed to contain the violation because it
    IS the measured segment, not a guess bracketed by padding.

    Strictly best-effort: search failures, empty results, near-full-clip hits
    (no localization value), and hits farther than SNAP_TOLERANCE_S from every
    Pegasus timestamp are all discarded, leaving the timestamp-padding path.
    """
    if client.mock:
        return  # fixture search clips predate the findings; nothing to measure against
    for f in analysis.findings:
        if not f.evidence:
            continue
        try:
            clips = client.search(index_id, f.evidence, ["visual", "audio"],
                                  page_limit=10, video_id=video_id)
        except Exception:
            continue
        stamps = [float(t) for t in f.timestamps]
        accepted: List[List[float]] = []
        for c in clips:
            try:
                s, e = float(c["start"]), float(c["end"])
            except (KeyError, TypeError, ValueError):
                continue
            span_len = e - s
            if span_len <= 0 or span_len > MAX_SPAN_S:
                continue
            if duration_s and span_len >= MAX_SPAN_FRACTION * duration_s:
                continue
            # Only trust a clip that corroborates one of the model's own
            # timestamps; a match elsewhere in the video is a different moment.
            if stamps and all(
                (t < s - SNAP_TOLERANCE_S or t > e + SNAP_TOLERANCE_S) for t in stamps
            ):
                continue
            accepted.append([s, e])
            if len(accepted) >= 3:
                break
        f.spans = accepted


def load_config() -> Dict[str, Any]:
    policies = yaml.safe_load((CONFIG / "policies.yaml").read_text())
    brief = yaml.safe_load((CONFIG / "campaign_brief.yaml").read_text())
    return {"policies": policies, "brief": brief}


def review_video(
    client: TwelveLabsClient,
    index_id: str,
    video_path: str,
    cfg: Dict[str, Any],
    on_stage: Optional[Callable[[int], None]] = None,
    brief_override: Optional[str] = None,
    guidance: Optional[str] = None,
    duration_s: Optional[float] = None,
) -> Tuple[ComplianceResult, str]:
    """Run one creative end to end. Returns (result, video_id).

    on_stage(i) is called as each stage begins so the API can stream live
    progress to the reviewer. brief_override lets each campaign supply its own
    brief (used by the relevance gate and the reasoning pass). guidance is
    optional advertiser free-text appended to the reasoning prompt.
    """
    policy_cfg = cfg["policies"]
    brief_cfg = cfg["brief"]
    policies = policy_cfg["policies"]
    brief_text = brief_override or brief_cfg["brief"]

    def _stage(i: int) -> None:
        if on_stage:
            on_stage(i)

    # Stage 0: ingest and index (mock returns deterministic ids).
    _stage(STAGE_INDEXING)
    task_id = client.upload_and_index(index_id, video_path)
    video_ref = client.wait_for_index(task_id)

    # Stages 1-2: Pegasus reads the campaign brief and the video, returning the
    # description, on-brief judgement, a 0-1 relevance score, and per-policy
    # findings in one pass. (Marengo 3.0 search no longer returns a numeric score,
    # so relevance is judged by the model against the campaign brief, not by a
    # Marengo search of generic signals.)
    _stage(STAGE_RELEVANCE)
    _stage(STAGE_ANALYZING)
    analysis = run_analysis(client, video_ref, policies, brief_text, guidance or "",
                            duration_s=duration_s)
    relevance = max(0.0, min(1.0, float(analysis.relevance_score)))

    # Stage 3: timestamped evidence. The findings come from Pegasus, but its
    # timestamps are generated estimates; snap each one onto the clip
    # boundaries Marengo actually measured while indexing (see
    # refine_timestamps) so the evidence points at the moment, not near it.
    _stage(STAGE_EVIDENCE)
    refine_timestamps(client, index_id, video_ref, analysis, duration_s=duration_s)

    # Stage 4: deterministic decision.
    _stage(STAGE_DECIDING)
    result = evaluate(
        video_ref=Path(video_path).name,
        analysis=analysis,
        policies=policies,
        relevance=relevance,
        relevance_threshold=policy_cfg.get("relevance_threshold", 0.55),
        auto_decision_min_confidence=policy_cfg.get("auto_decision_min_confidence", "medium"),
        duration_s=duration_s,
    )
    return result, video_ref
