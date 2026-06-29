"""
Pipeline orchestrator.

Wires the stages in order for one video:

  ingest/index  ->  relevance gate  ->  Pegasus reasoning  ->  Marengo evidence
                ->  deterministic decision  ->  GreenlightResult

In production this is one worker pulling from a queue. Indexing is async (submit,
then resume on the index.task.ready webhook). Here we run it inline for clarity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from .analyze import run_analysis
from .client import TwelveLabsClient
from .decision import evaluate
from .relevance import relevance_score
from .schemas import GreenlightResult
from .search import run_search_probes

CONFIG = Path(__file__).resolve().parent.parent / "config"


def load_config() -> Dict[str, Any]:
    policies = yaml.safe_load((CONFIG / "policies.yaml").read_text())
    brief = yaml.safe_load((CONFIG / "campaign_brief.yaml").read_text())
    return {"policies": policies, "brief": brief}


def review_video(
    client: TwelveLabsClient,
    index_id: str,
    video_path: str,
    cfg: Dict[str, Any],
) -> GreenlightResult:
    policy_cfg = cfg["policies"]
    brief_cfg = cfg["brief"]
    policies = policy_cfg["policies"]

    # Stage 0: ingest and index (mock returns deterministic ids).
    task_id = client.upload_and_index(index_id, video_path)
    video_ref = client.wait_for_index(task_id)

    # Stage 1: relevance gate.
    relevance = relevance_score(client, video_ref, brief_cfg.get("positive_signals", []))

    # Stage 2: Pegasus structured reasoning.
    analysis = run_analysis(client, video_ref, policies, brief_cfg["brief"])

    # Stage 3: Marengo timestamped evidence.
    evidence = run_search_probes(client, video_ref, policies)

    # Stage 4: deterministic decision.
    result = evaluate(
        video_ref=Path(video_path).name,
        analysis=analysis,
        search_evidence=evidence,
        policies=policies,
        relevance=relevance,
        relevance_threshold=policy_cfg.get("relevance_threshold", 0.55),
        auto_decision_min_confidence=policy_cfg.get("auto_decision_min_confidence", "medium"),
    )
    return result
