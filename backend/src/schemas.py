"""
Data contracts for Greenlight.

Two things live here:

1. PEGASUS_ANALYZE_SCHEMA: the JSON Schema we send to the TwelveLabs /analyze
   endpoint via response_format. This forces Pegasus to return machine-readable
   findings instead of prose, which is what makes the output usable by a
   deterministic decision engine. Per the TwelveLabs docs, the schema takes
   precedence over the prompt, so the schema is the real contract.

2. Pydantic models: typed objects the rest of the pipeline passes around. We
   validate the model output against these so a malformed or truncated response
   fails loudly instead of silently corrupting a compliance decision.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"


class Decision(str, Enum):
    approve = "APPROVE"
    review = "REVIEW"
    block = "BLOCK"


class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# Ordering helpers so the decision engine can compare severities and confidences.
SEVERITY_ORDER = {Severity.none: 0, Severity.low: 1, Severity.medium: 2, Severity.high: 3}
CONFIDENCE_ORDER = {Confidence.low: 0, Confidence.medium: 1, Confidence.high: 2}


class PegasusFinding(BaseModel):
    """A single policy finding produced by the Pegasus reasoning pass."""
    category: str = Field(..., description="Policy id, e.g. unsafe_usage")
    severity: Severity
    evidence: str = Field("", description="Short natural-language justification")
    timestamps: List[float] = Field(default_factory=list, description="Seconds into the video")


class PegasusAnalysis(BaseModel):
    """The full structured object Pegasus returns for one video."""
    description: str = Field(..., description="2 to 5 sentence neutral description of the video")
    on_brief: bool
    on_brief_rationale: str = ""
    relevance_score: float = Field(0.5, description="0 to 1, how strongly the video matches the campaign brief")
    findings: List[PegasusFinding] = Field(default_factory=list)


class SearchEvidence(BaseModel):
    """A timestamped clip returned by the Marengo search pass."""
    policy_id: str
    query: str
    start: float
    end: float
    score: float
    confidence: Confidence


class PolicyVerdict(BaseModel):
    """Per-policy outcome after combining reasoning and search evidence."""
    policy_id: str
    label: str
    severity: Severity
    triggered: bool
    contribution: str            # APPROVE | REVIEW | BLOCK that this policy pushes toward
    evidence: List[SearchEvidence] = Field(default_factory=list)
    note: str = ""


class GreenlightResult(BaseModel):
    """The final, demo-facing result for one video."""
    video_ref: str
    decision: Decision
    confidence: Confidence
    description: str
    on_brief: bool
    on_brief_rationale: str = ""
    relevance_score: float
    reasons: List[str] = Field(default_factory=list)
    policy_verdicts: List[PolicyVerdict] = Field(default_factory=list)
    human_review_required: bool = False


# JSON Schema sent to Pegasus. Kept deliberately tight: a small number of
# required fields, an enum on severity so we never get a free-text level we
# cannot map. minItems is restricted to 0 or 1 in the TwelveLabs schema dialect,
# so we do not over-constrain array lengths.
PEGASUS_ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "A neutral 2 to 5 sentence description of what happens in the video.",
        },
        "on_brief": {
            "type": "boolean",
            "description": "True if the video genuinely features the campaign product.",
        },
        "on_brief_rationale": {
            "type": "string",
            "description": "One sentence explaining the on_brief judgement.",
        },
        "relevance_score": {
            "type": "number",
            "description": "0 to 1: how strongly the video matches the campaign brief (1 = clearly on-brief and about the product, 0 = unrelated).",
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "One of the policy ids provided in the prompt.",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["none", "low", "medium", "high"],
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Short justification grounded in the video.",
                    },
                    "timestamps": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Seconds into the video where this occurs.",
                    },
                },
                "required": ["category", "severity"],
            },
        },
    },
    "required": ["description", "on_brief", "findings"],
}
