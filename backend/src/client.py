"""
Thin client over the TwelveLabs REST API (v1.3), verified against the live docs
(June 2026). Endpoints: POST /indexes, POST /tasks, GET /tasks/{id},
POST /search, POST /analyze.

Design:
  * Direct httpx against the documented REST endpoints — explicit control over
    timeouts, retries (429 backoff) and error handling.
  * Every network call has a mock counterpart. With no API key the whole
    pipeline runs on fixtures, so the app works end to end before a key is set;
    drop in a real key and the same code path hits TwelveLabs.

Verified model names:
  * marengo3.0  — search / embedding (create-index + /search)
  * pegasus1.2  — generation at index creation
  * pegasus1.5  — selectable per /analyze request (better reasoning)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

BASE_URL = os.environ.get("TL_BASE_URL", "https://api.twelvelabs.io/v1.3")
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

ANALYZE_MODEL = os.environ.get("TL_ANALYZE_MODEL", "pegasus1.2")
SCENARIOS = ("clean_tutorial", "eye_misuse_claim", "mild_profanity", "offbrief_clickbait")


class TwelveLabsError(RuntimeError):
    pass


class TwelveLabsClient:
    def __init__(self, api_key: Optional[str] = None, mock: Optional[bool] = None):
        self.api_key = api_key or os.environ.get("TL_API_KEY")
        self.mock = (mock if mock is not None else not bool(self.api_key))
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"x-api-key": self.api_key or "", "Content-Type": "application/json"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    # --- small retry wrapper so a 429 does not kill a compliance run ---------
    def _post(self, path: str, **kw) -> httpx.Response:
        for attempt in range(4):
            resp = self._http.post(path, **kw)
            if resp.status_code == 429 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise TwelveLabsError(f"{path} -> {resp.status_code}: {resp.text[:300]}")
            return resp
        return resp  # pragma: no cover

    def _post_multipart(self, path: str, parts) -> httpx.Response:
        """POST multipart/form-data (v1.3 wants this for /tasks and /search).
        Uses a bare client so httpx sets the multipart boundary itself."""
        for attempt in range(4):
            resp = httpx.post(f"{BASE_URL}{path}", headers={"x-api-key": self.api_key},
                              files=parts, timeout=httpx.Timeout(60.0, connect=10.0))
            if resp.status_code == 429 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise TwelveLabsError(f"{path} -> {resp.status_code}: {resp.text[:300]}")
            return resp
        return resp  # pragma: no cover

    # --------------------------------------------------------------- indexes
    def validate(self) -> bool:
        """Cheap authenticated check used to verify a key before we store it.
        GET /indexes is authenticated and side-effect-free."""
        if self.mock:
            return True
        resp = self._http.get("/indexes")
        if resp.status_code == 401:
            raise TwelveLabsError("API key is invalid or expired")
        if resp.status_code >= 400:
            raise TwelveLabsError(f"/indexes -> {resp.status_code}: {resp.text[:200]}")
        return True

    def find_index(self, name: str = "clearframe-index") -> Optional[str]:
        """Return the _id of an existing index with this name, or None."""
        if self.mock:
            return "mock-index"
        data = self._http.get("/indexes").json().get("data", [])
        for ix in data:
            if ix.get("index_name") == name:
                return ix.get("_id")
        return None

    def create_index(self, name: str = "clearframe-index") -> str:
        """Create an index with Marengo (search) + Pegasus (generation) enabled."""
        if self.mock:
            return "mock-index"
        payload = {
            "index_name": name,
            "models": [
                {"model_name": "marengo3.0", "model_options": ["visual", "audio"]},
                {"model_name": "pegasus1.2", "model_options": ["visual", "audio"]},
            ],
            "addons": ["thumbnail"],
        }
        return self._post("/indexes", json=payload).json()["_id"]

    # ---------------------------------------------------------------- ingest
    def upload_and_index(self, index_id: str, video_path: str) -> str:
        """Submit a video for indexing. Returns a task id. Accepts a local file
        path or an http(s) URL (TwelveLabs ingests both). /tasks requires
        multipart/form-data in BOTH cases, so text fields are sent as multipart
        parts via (None, value) tuples."""
        if self.mock:
            return f"mock-task-{Path(video_path).stem}"
        fields = {"index_id": (None, index_id), "enable_video_stream": (None, "true")}
        if str(video_path).startswith(("http://", "https://")):
            fields["video_url"] = (None, video_path)
            resp = httpx.post(f"{BASE_URL}/tasks", headers={"x-api-key": self.api_key},
                              files=fields, timeout=httpx.Timeout(300.0, connect=10.0))
        else:
            with open(video_path, "rb") as fh:
                fields["video_file"] = (Path(video_path).name, fh, "video/mp4")
                resp = httpx.post(f"{BASE_URL}/tasks", headers={"x-api-key": self.api_key},
                                  files=fields, timeout=httpx.Timeout(600.0, connect=10.0))
        if resp.status_code >= 400:
            raise TwelveLabsError(f"/tasks -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()["_id"]

    def wait_for_index(self, task_id: str, poll_seconds: int = 5, timeout: int = 1800) -> str:
        """Poll GET /tasks/{id} until ready; return the video_id."""
        if self.mock:
            return f"mock-video-{task_id.split('mock-task-')[-1]}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self._http.get(f"/tasks/{task_id}")
            if resp.status_code >= 400:
                raise TwelveLabsError(f"/tasks/{task_id} -> {resp.status_code}: {resp.text[:200]}")
            body = resp.json()
            status = body.get("status")
            if status == "ready":
                return body["video_id"]
            if status == "failed":
                raise TwelveLabsError(f"Indexing failed for task {task_id}")
            time.sleep(poll_seconds)
        raise TimeoutError(f"Indexing timed out for task {task_id}")

    # --------------------------------------------------------------- analyze
    def analyze(self, video_id: str, prompt: str, json_schema: Dict[str, Any],
                model_name: str = ANALYZE_MODEL, temperature: float = 0.2,
                max_tokens: int = 4096) -> Dict[str, Any]:
        """Structured Pegasus analysis. The live /analyze does not reliably honour
        response_format, so we ask for JSON in the prompt and parse it from the
        returned text, the robust, model-agnostic way to get structured output.
        max_tokens defaults to Pegasus 1.2's own response ceiling, so a video with
        many findings gets the most room available before the response is cut off.

        Occasionally the model's own JSON is malformed (an unescaped quote inside
        an evidence string is the usual culprit) - non-deterministic, not caused
        by the input, so a second call very often comes back clean. Retries once
        on a parse failure before giving up; the video is already indexed, so a
        retry only re-runs the analysis call, not the indexing."""
        if self.mock:
            return self._mock_analyze(video_id)
        payload = {"video_id": video_id, "model_name": model_name, "prompt": prompt,
                   "temperature": temperature, "max_tokens": max_tokens, "stream": False}
        last_err = None
        for attempt in range(2):
            body = self._post("/analyze", json=payload).json()
            if body.get("finish_reason") == "length":
                raise ValueError(f"Pegasus response truncated (finish_reason=length) even at "
                                  f"max_tokens={max_tokens}; the findings list is likely too long, "
                                  f"tighten the prompt or shorten evidence strings")
            raw = body.get("data", "")
            try:
                return _extract_json(raw)
            except Exception as exc:
                last_err = exc
                # Never discard the offending text silently - this is the only
                # place it exists, and without it a parse failure is undiagnosable.
                print(f"[analyze] JSON parse failed (attempt {attempt + 1}/2): {exc}\n"
                      f"[analyze] raw response ({len(raw)} chars): {raw[:1500]}")
        raise ValueError(f"Pegasus returned malformed JSON twice in a row: {last_err}")

    def ask(self, video_id: str, question: str, analysis_context: str = "", model_name: str = ANALYZE_MODEL) -> str:
        """Chat over two sources: the video itself (Pegasus reads it) AND ClearFrame's
        structured analysis, injected as prompt context. Not RAG — the analysis is
        small and structured, so we stuff it directly. Seeded demo creatives carry a
        `mock-` video id, so their chat stays answerable from fixtures."""
        if self.mock or str(video_id).startswith("mock-"):
            return self._mock_ask(video_id, question)
        prompt = (
            "You are ClearFrame's compliance copilot helping a human reviewer who is short on time. "
            "Answer the question using BOTH the video itself and the automated compliance analysis below. "
            "If the analysis includes a line about Marengo index search matches, those are measured clip "
            "times, not estimates, prefer them over a guessed timestamp when both point at the same moment.\n\n"
            "STRICT response format:\n"
            "  - 2 to 3 short bullet points, each starting with '- '.\n"
            "  - Write like a sharp colleague giving a quick answer out loud, not like a report. Plain\n"
            "    words, active voice, no jargon unless the reviewer's question used it first.\n"
            "  - Each bullet is one sentence, about 15 to 25 words. Shorter is better than padded.\n"
            "  - Cite a timestamp (seconds) in a bullet only when it is grounded in the analysis or video.\n"
            "  - No preamble, no restating the question, no filler, no hedging ('it appears that', 'it\n"
            "    seems'), no AI-assistant phrasing ('I'd be happy to', 'let me know if').\n\n"
            f"--- ClearFrame analysis ---\n{analysis_context or '(none)'}\n--- end analysis ---\n\n"
            f"Reviewer question: {question}"
        )
        payload = {"video_id": video_id, "model_name": model_name, "prompt": prompt,
                   "temperature": 0.2, "stream": False}
        return self._post("/analyze", json=payload).json()["data"]

    # ---------------------------------------------------------------- search
    def search(self, index_id: str, query_text: str, modalities: List[str],
               page_limit: int = 5, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Marengo semantic search. When video_id is given, results are scoped to
        that video SERVER-SIDE via the filter param - critical on a shared index,
        where the global top-N for a common word ("damn") is easily monopolised
        by other videos, leaving zero results for the one being analysed after a
        client-side filter. (Confirmed live: 5/5 global hits for a one-word query
        were other uploads; the scoped query returned the right clips.) The
        client-side filter stays as a belt-and-braces check. Marengo 3.0: 'audio'
        is non-speech, 'transcription' is speech, so an audio probe is widened to
        catch spoken content too."""
        if self.mock:
            return self._mock_search(video_id or index_id, query_text)
        opts = set(modalities)
        if "audio" in opts:
            opts.add("transcription")
        parts = [("index_id", (None, index_id)), ("query_text", (None, query_text)),
                 ("page_limit", (None, str(page_limit))), ("group_by", (None, "clip")),
                 ("operator", (None, "or"))]
        if video_id:
            parts.append(("filter", (None, json.dumps({"id": [video_id]}))))
        for o in opts:
            parts.append(("search_options", (None, o)))
        data = self._post_multipart("/search", parts).json().get("data", [])
        if video_id:
            data = [d for d in data if d.get("video_id") == video_id]
        return data

    # ------------------------------------------------------------ mock layer
    def _mock_analyze(self, video_ref: str) -> Dict[str, Any]:
        return json.loads((FIXTURES / "analyze" / f"{_fixture_key(video_ref)}.json").read_text())

    def _mock_search(self, ref: str, query_text: str) -> List[Dict[str, Any]]:
        path = FIXTURES / "search" / f"{_fixture_key(ref)}.json"
        if not path.exists():
            return []
        records = json.loads(path.read_text())
        return [r["hit"] for r in records if r["query"] == query_text]

    def _mock_ask(self, video_ref: str, prompt: str) -> str:
        """Synthesise a grounded answer from the recorded analysis fixture."""
        a = self._mock_analyze(video_ref)
        q = prompt.lower()
        flagged = [f for f in a.get("findings", []) if f.get("severity") not in (None, "none")]
        if any(w in q for w in ("where", "when", "timestamp", "moment", "clip")):
            if not flagged:
                return "No flagged moments, the creative is clean across the full timeline."
            return "Flagged moments:\n" + "\n".join(
                f"• ~{int(f.get('timestamps', [0])[0])}s {f['category']}: {f.get('evidence','')}" for f in flagged)
        if any(w in q for w in ("brief", "relevan")):
            return f"On-brief: {a.get('on_brief')}. {a.get('on_brief_rationale','')}"
        if any(w in q for w in ("summar", "describe", "what happens")):
            return a.get("description", "")
        if flagged:
            return f"{len(flagged)} policy area(s) flagged: " + ", ".join(f["category"] for f in flagged) + ". " + a.get("description", "")
        return a.get("description", "I could not find anything notable in this creative.")


import re as _re


def _strip_trailing_commas(t: str) -> str:
    """Remove a comma that appears right before a closing ] or }, ignoring
    whitespace/newlines between them. The single most common way an LLM's
    otherwise-correct JSON breaks (it writes one item per line and leaves the
    comma from the previous line when it decides that was the last item)."""
    return _re.sub(r",(\s*[\]}])", r"\1", t)


def _extract_json(text: str) -> Dict[str, Any]:
    """Pull a JSON object out of Pegasus prose (handles ```json fences / preamble).
    Tries a straight parse first, then a couple of cheap, safe repairs before
    giving up - each is a pure syntax fix (never touches string content), so
    they can only turn invalid JSON into the JSON that was clearly intended."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = _re.sub(r"^```(?:json)?", "", t).strip()
        if t.endswith("```"):
            t = t[:-3].strip()
    candidates = [t]
    m = _re.search(r"\{.*\}", t, _re.S)
    if m and m.group(0) != t:
        candidates.append(m.group(0))
    candidates += [_strip_trailing_commas(c) for c in list(candidates)]
    last_err = None
    for c in candidates:
        try:
            return json.loads(c)
        except Exception as exc:
            last_err = exc
    raise last_err if last_err else ValueError(f"Pegasus did not return JSON: {text[:200]}")


def _fixture_key(ref: str) -> str:
    for scenario in SCENARIOS:
        if scenario in (ref or ""):
            return scenario
    return "clean_tutorial"
