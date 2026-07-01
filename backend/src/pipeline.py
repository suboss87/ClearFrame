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
    analysis = run_analysis(client, video_ref, policies, brief_text, guidance or "")
    relevance = max(0.0, min(1.0, float(analysis.relevance_score)))

    # Stage 3: timestamped evidence — taken from the Pegasus findings themselves
    # (Marengo 3.0 search returns no score to corroborate by, so the model's
    # multimodal findings + timestamps are the evidence).
    _stage(STAGE_EVIDENCE)

    # Stage 4: deterministic decision.
    _stage(STAGE_DECIDING)
    result = evaluate(
        video_ref=Path(video_path).name,
        analysis=analysis,
        search_evidence={},
        policies=policies,
        relevance=relevance,
        relevance_threshold=policy_cfg.get("relevance_threshold", 0.55),
        auto_decision_min_confidence=policy_cfg.get("auto_decision_min_confidence", "medium"),
    )
    return result, video_ref
