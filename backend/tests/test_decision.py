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


def test_high_severity_block_is_high_confidence_with_timestamped_evidence():
    # A high-severity finding blocks at high confidence, and its evidence is
    # taken straight from the model finding's own timestamps (Marengo 3.0 search
    # returns no score to corroborate by).
    findings = [PegasusFinding(category="unsafe_usage", severity=Severity.high,
                               evidence="product applied to the eyeball", timestamps=[10.0, 22.0])]
    r = evaluate("v.mp4", _analysis(findings=findings), {}, POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    assert r.decision == Decision.block
    assert r.confidence == Confidence.high
    # One evidence row per finding, spanning first..last timestamp (no per-second dupes).
    pv = next(v for v in r.policy_verdicts if v.policy_id == "unsafe_usage")
    assert len(pv.evidence) == 1
    assert pv.evidence[0].start == 10.0 and pv.evidence[0].end == 24.0


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
