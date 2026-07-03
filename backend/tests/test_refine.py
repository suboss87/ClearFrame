"""
Tests for Marengo evidence refinement (pipeline.refine_timestamps).

Pegasus estimates timestamps; Marengo measures clip boundaries. The refinement
attaches trustworthy measured spans to each finding (finding.spans), which the
decision engine then prefers over timestamp padding. These tests prove the
acceptance rules: a clip must corroborate one of the model's own timestamps,
must actually localize (not span most of the video), and any failure leaves
spans empty so the timestamp-padding fallback still applies.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import refine_timestamps
from src.schemas import PegasusAnalysis, PegasusFinding, Severity


class StubClient:
    mock = False

    def __init__(self, clips=None, raises=False):
        self._clips = clips or []
        self._raises = raises

    def search(self, index_id, query_text, modalities, page_limit=5, video_id=None):
        if self._raises:
            raise RuntimeError("search down")
        return self._clips


def _analysis(timestamps):
    return PegasusAnalysis(
        description="d", on_brief=True, on_brief_rationale="r",
        findings=[PegasusFinding(category="profanity", severity=Severity.low,
                                 evidence="a swear word", timestamps=timestamps)],
    )


def test_measured_clip_near_estimate_is_attached():
    # Pegasus said 2.5s; Marengo measured the matching clip at 0.16-4.48. The
    # estimate falls inside, so the measured span is trusted and attached.
    a = _analysis([2.5])
    refine_timestamps(StubClient(clips=[{"start": 0.16, "end": 4.48}]), "idx", "vid", a,
                      duration_s=10.0)
    assert a.findings[0].spans == [[0.16, 4.48]]


def test_near_full_clip_hit_carries_no_localization():
    # "The whole video matches" is not a measurement of WHERE; discard it and
    # keep the tighter clip only.
    a = _analysis([2.5])
    refine_timestamps(StubClient(clips=[{"start": 0.0, "end": 10.0},
                                        {"start": 0.16, "end": 4.48}]), "idx", "vid", a,
                      duration_s=10.0)
    assert a.findings[0].spans == [[0.16, 4.48]]


def test_far_away_hit_is_not_trusted():
    # The only hit is 20+ seconds from every Pegasus timestamp - a different
    # part of the video. Attaching it would move evidence AWAY from the
    # violation, so spans stay empty and the timestamp fallback applies.
    a = _analysis([2.5])
    refine_timestamps(StubClient(clips=[{"start": 28.0, "end": 30.0}]), "idx", "vid", a,
                      duration_s=60.0)
    assert a.findings[0].spans == []


def test_search_failure_leaves_spans_empty():
    a = _analysis([3.0, 9.0])
    refine_timestamps(StubClient(raises=True), "idx", "vid", a, duration_s=10.0)
    assert a.findings[0].spans == []
    assert a.findings[0].timestamps == [3.0, 9.0]  # estimates untouched


def test_mock_client_skips_refinement():
    stub = StubClient(clips=[{"start": 0.0, "end": 1.0}])
    stub.mock = True
    a = _analysis([8.0])
    refine_timestamps(stub, "idx", "vid", a, duration_s=10.0)
    assert a.findings[0].spans == []


def test_at_most_three_spans_kept():
    clips = [{"start": float(i), "end": float(i) + 1.0} for i in range(6)]
    a = _analysis([0.5, 2.5, 4.5])
    refine_timestamps(StubClient(clips=clips), "idx", "vid", a, duration_s=60.0)
    assert len(a.findings[0].spans) == 3


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
