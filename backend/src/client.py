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
        path or an http(s) URL (TwelveLabs ingests both)."""
        if self.mock:
            return f"mock-task-{Path(video_path).stem}"
        data = {"index_id": index_id, "enable_video_stream": "true"}
        if str(video_path).startswith(("http://", "https://")):
            data["video_url"] = video_path
            resp = httpx.post(f"{BASE_URL}/tasks", headers={"x-api-key": self.api_key}, data=data,
                              timeout=httpx.Timeout(300.0, connect=10.0))
        else:
            with open(video_path, "rb") as fh:
                resp = httpx.post(f"{BASE_URL}/tasks", headers={"x-api-key": self.api_key},
                                  data=data, files={"video_file": fh},
                                  timeout=httpx.Timeout(600.0, connect=10.0))
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
                model_name: str = ANALYZE_MODEL, temperature: float = 0.2) -> Dict[str, Any]:
        """Structured Pegasus analysis via response_format json_schema."""
        if self.mock:
            return self._mock_analyze(video_id)
        payload = {
            "video_id": video_id, "model_name": model_name, "prompt": prompt,
            "temperature": temperature, "stream": False,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "compliance_report", "schema": json_schema}},
        }
        body = self._post("/analyze", json=payload).json()
        if body.get("finish_reason") == "length":
            raise ValueError("Pegasus response truncated (finish_reason=length); raise max_tokens")
        data = body["data"]
        return json.loads(data) if isinstance(data, str) else data

    def ask(self, video_id: str, prompt: str, model_name: str = ANALYZE_MODEL) -> str:
        """Open-ended Q&A about a video (chat-with-video). Returns prose."""
        if self.mock:
            return self._mock_ask(video_id, prompt)
        payload = {"video_id": video_id, "model_name": model_name, "prompt": prompt,
                   "temperature": 0.2, "stream": False}
        return self._post("/analyze", json=payload).json()["data"]

    # ---------------------------------------------------------------- search
    def search(self, index_id: str, query_text: str, modalities: List[str],
               page_limit: int = 5, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Marengo semantic search. When video_id is given, results are scoped to
        that video. Marengo 3.0: 'audio' is non-speech, 'transcription' is speech,
        so an audio probe is widened to catch spoken content too."""
        if self.mock:
            return self._mock_search(video_id or index_id, query_text)
        opts = set(modalities)
        if "audio" in opts:
            opts.add("transcription")
        payload = {"index_id": index_id, "query_text": query_text,
                   "search_options": list(opts), "group_by": "clip",
                   "page_limit": page_limit, "operator": "or"}
        data = self._post("/search", json=payload).json().get("data", [])
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
                return "No flagged moments — the creative is clean across the full timeline."
            return "Flagged moments:\n" + "\n".join(
                f"• ~{int(f.get('timestamps', [0])[0])}s — {f['category']}: {f.get('evidence','')}" for f in flagged)
        if any(w in q for w in ("brief", "relevan")):
            return f"On-brief: {a.get('on_brief')}. {a.get('on_brief_rationale','')}"
        if any(w in q for w in ("summar", "describe", "what happens")):
            return a.get("description", "")
        if flagged:
            return f"{len(flagged)} policy area(s) flagged: " + ", ".join(f["category"] for f in flagged) + ". " + a.get("description", "")
        return a.get("description", "I could not find anything notable in this creative.")


def _fixture_key(ref: str) -> str:
    for scenario in SCENARIOS:
        if scenario in (ref or ""):
            return scenario
    return "clean_tutorial"
