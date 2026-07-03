"""
Tests for client._extract_json, the parser that turns Pegasus's text response
into the structured object the rest of the pipeline depends on.

Written after a live failure ("Expecting ',' delimiter") reached the reviewer
as an opaque pipeline error with the offending text discarded and no way to
diagnose it. These lock in the cheap, safe repairs added in response: they
fix pure JSON syntax (trailing commas, code fences, leading/trailing prose)
without ever touching what the model actually said.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.client import _extract_json


def test_clean_json_parses():
    assert _extract_json('{"a": 1, "b": [1, 2]}') == {"a": 1, "b": [1, 2]}


def test_markdown_fence_is_stripped():
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_leading_and_trailing_prose_is_stripped():
    text = 'Here is the analysis:\n{"a": 1}\nLet me know if you need more.'
    assert _extract_json(text) == {"a": 1}


def test_trailing_comma_before_closing_brace_is_repaired():
    # The most common way an otherwise-correct LLM response breaks: one item
    # per line, the model leaves the previous line's comma on the last item.
    text = '{"findings": [{"category": "profanity", "severity": "low"},]}'
    assert _extract_json(text) == {"findings": [{"category": "profanity", "severity": "low"}]}


def test_trailing_comma_before_closing_bracket_is_repaired():
    text = '{"timestamps": [1.0, 2.5,]}'
    assert _extract_json(text) == {"timestamps": [1.0, 2.5]}


def test_trailing_comma_with_newlines_is_repaired():
    text = '{\n  "a": 1,\n  "b": 2,\n}'
    assert _extract_json(text) == {"a": 1, "b": 2}


def test_genuinely_broken_json_raises_with_useful_message():
    # An unescaped quote inside a string value - not a syntax pattern any
    # cheap repair can safely fix, so this must still fail, but with the
    # actual parser error, not a swallowed/mangled one.
    text = '{"evidence": "she says "get ready" on camera"}'
    try:
        _extract_json(text)
        assert False, "expected a parse error"
    except Exception as exc:
        assert "Expecting" in str(exc) or "delimiter" in str(exc)


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
