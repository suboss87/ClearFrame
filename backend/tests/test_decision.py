"""
Tests for the decision engine.

These exist to make one point: because the verdict is deterministic,
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
    r = evaluate("v.mp4", _analysis(), POLICIES, relevance=0.9, relevance_threshold=0.55)
    assert r.decision == Decision.approve
    assert r.confidence == Confidence.high


def test_offbrief_blocks():
    r = evaluate("v.mp4", _analysis(on_brief=False), POLICIES,
                 relevance=0.2, relevance_threshold=0.55)
    assert r.decision == Decision.block
    assert "Off-brief" in r.reasons[0]


def test_high_severity_unsafe_usage_blocks():
    findings = [PegasusFinding(category="unsafe_usage", severity=Severity.high, evidence="eye")]
    r = evaluate("v.mp4", _analysis(findings=findings), POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    assert r.decision == Decision.block


def test_low_profanity_routes_to_review():
    findings = [PegasusFinding(category="profanity", severity=Severity.low, evidence="swear")]
    r = evaluate("v.mp4", _analysis(findings=findings), POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    assert r.decision == Decision.review
    assert r.human_review_required is True


def test_high_severity_block_is_high_confidence_with_timestamped_evidence():
    # A high-severity finding blocks at high confidence, and its evidence is
    # taken straight from the model finding's own timestamps (Marengo 3.0 search
    # returns no score to corroborate by).
    findings = [PegasusFinding(category="unsafe_usage", severity=Severity.high,
                               evidence="product applied to the eyeball", timestamps=[10.0, 22.0])]
    r = evaluate("v.mp4", _analysis(findings=findings), POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    assert r.decision == Decision.block
    assert r.confidence == Confidence.high
    # Timestamps far apart are distinct moments of the same violation, so each
    # gets its own clickable evidence row. Each row is padded 1s before and
    # after the reported second, so a reviewer sees the lead-in and the
    # aftermath, not just playback starting exactly as it happens.
    pv = next(v for v in r.policy_verdicts if v.policy_id == "unsafe_usage")
    assert len(pv.evidence) == 2
    assert pv.evidence[0].start == 9.0 and pv.evidence[0].end == 11.0
    assert pv.evidence[1].start == 21.0 and pv.evidence[1].end == 23.0


def test_nearby_timestamps_merge_into_one_evidence_row():
    # Timestamps within the evidence window describe one continuous moment and
    # must NOT be split into separate rows.
    findings = [PegasusFinding(category="unsafe_usage", severity=Severity.high,
                               evidence="eye contact", timestamps=[10.0, 11.5])]
    r = evaluate("v.mp4", _analysis(findings=findings), POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    pv = next(v for v in r.policy_verdicts if v.policy_id == "unsafe_usage")
    assert len(pv.evidence) == 1
    assert pv.evidence[0].start == 9.0 and pv.evidence[0].end == 12.5


def test_evidence_padding_never_goes_negative():
    # A violation reported near the very start of the clip must not produce a
    # negative seek target.
    findings = [PegasusFinding(category="unsafe_usage", severity=Severity.high,
                               evidence="eye contact", timestamps=[0.3])]
    r = evaluate("v.mp4", _analysis(findings=findings), POLICIES,
                 relevance=0.8, relevance_threshold=0.55)
    pv = next(v for v in r.policy_verdicts if v.policy_id == "unsafe_usage")
    assert pv.evidence[0].start == 0.0 and pv.evidence[0].end == 1.3


def test_measured_spans_take_priority_over_timestamp_padding():
    # When Marengo measured the clip containing the violation, the evidence
    # window IS that measurement (small symmetric pad), not a padded guess -
    # the real case: Pegasus said 2.5s, the word was at ~4s, the measured clip
    # 0.16-4.48 contains it; the padded 1.5-3.5 window did not.
    f = PegasusFinding(category="profanity", severity=Severity.low,
                       evidence="damn", timestamps=[2.5])
    f.spans = [[0.16, 4.48]]
    r = evaluate("v.mp4", _analysis(findings=[f]), POLICIES,
                 relevance=0.8, relevance_threshold=0.55, duration_s=10.0)
    pv = next(v for v in r.policy_verdicts if v.policy_id == "profanity")
    assert len(pv.evidence) == 1
    assert pv.evidence[0].start == 0.0        # 0.16 - 0.5 floored at 0
    assert pv.evidence[0].end == 4.98         # 4.48 + 0.5, inside the 10s clip


def test_evidence_padding_clamped_to_known_duration():
    # A violation reported near the end of the clip must not seek past the
    # video's actual runway when the pipeline knows how long the clip is.
    findings = [PegasusFinding(category="unsafe_usage", severity=Severity.high,
                               evidence="eye contact", timestamps=[9.5])]
    r = evaluate("v.mp4", _analysis(findings=findings), POLICIES,
                 relevance=0.8, relevance_threshold=0.55, duration_s=10.0)
    pv = next(v for v in r.policy_verdicts if v.policy_id == "unsafe_usage")
    assert pv.evidence[0].start == 8.5 and pv.evidence[0].end == 10.0


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
