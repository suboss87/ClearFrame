"""
Tests for the decision engine.

These exist to make one point in the panel: because the verdict is deterministic,
it is unit-testable. We can prove that a given set of signals always produces the
same call. You cannot write a test like this against "ask the LLM to decide".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.decision import evaluate
from src.schemas import (
    Confidence,
    Decision,
    PegasusAnalysis,
    PegasusFinding,
    SearchEvidence,
    Severity,
)

POLICIES = [
    {"id": "profanity", "label": "Profanity", "garm_floor": False,
     "suitability_tier": "medium", "block_at": "high", "review_at": "low"},
    {"id": "unsafe_usage", "label": "Unsafe usage", "garm_floor": False,
     "suitability_tier": "high", "block_at": "medium", "review_at": "low"},
    {"id": "medical_claims", "label": "Medical claims", "garm_floor": False,
     "suitability_tier": "high", "block_at": "medium", "review_at": "low"},
    {"id": "hate_harassment", "label": "Hate", "garm_floor": True,
     "suitability_tier": "high", "block_at": "medium", "review_at": "low"},
]


def _analysis(on_brief=True, findings=None):
    return PegasusAnalysis(
        description="desc", on_brief=on_brief, on_brief_rationale="r",
        findings=findings or [],
    )


def test_clean_video_approves():
    r = evaluate("v.mp4", _analysis(), {}, POLICIES, relevance=0.9, relevance_threshold=0.55)
    assert r.decision == Decision.approve
    assert r.confidence == Confidence.high


def test_offbrief_blocks():
    r = evaluate("v.mp4", _analysis(on_brief=False), {}, POLICIES,
                 relevance=0.2, relevance_threshold=0.55)
    assert r.decision == Decision.block
    assert "Off-brief" in r.reasons[0]


def test_high_severity_unsafe_usage_blocks():
    findings = [PegasusFinding(category="unsafe_usage", severity=Severity.high, evidence="eye")]
    r = evaluate("v.mp4", _analysis(findings=findings), {}, POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    assert r.decision == Decision.block


def test_low_profanity_routes_to_review():
    findings = [PegasusFinding(category="profanity", severity=Severity.low, evidence="swear")]
    r = evaluate("v.mp4", _analysis(findings=findings), {}, POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    assert r.decision == Decision.review
    assert r.human_review_required is True


def test_corroboration_lifts_confidence_to_high():
    findings = [PegasusFinding(category="unsafe_usage", severity=Severity.medium, evidence="eye")]
    evidence = {"unsafe_usage": [SearchEvidence(
        policy_id="unsafe_usage", query="eye", start=10, end=14, score=80, confidence=Confidence.high)]}
    r = evaluate("v.mp4", _analysis(findings=findings), evidence, POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    assert r.decision == Decision.block
    assert r.confidence == Confidence.high


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
