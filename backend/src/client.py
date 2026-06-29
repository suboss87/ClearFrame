"""
Thin client over the TwelveLabs REST API (v1.3).

Design choices worth defending in the panel:

  * We talk to the documented REST endpoints directly with httpx rather than
    leaning on the SDK surface. Reason: it gives us explicit control over
    timeouts, retries and error handling, and it insulates us from SDK method
    renames (the published SDK reference has lagged the API). The official SDK
    is a fine alternative for a quick script; for a pipeline that gates revenue
    we want the control.

  * Every network call has a mock counterpart. MOCK mode loads fixtures so the
    whole pipeline runs in CI and in a live demo without an API key, without
    upload latency, and without spending quota. This is not a shortcut, it is
    how you make an integration testable. In a real deployment the fixtures
    become contract tests against recorded responses.

Verify before the interview (the API moves fast):
  * base URL / version (v1.3 at time of writing)
  * model names: marengo3.0 for indexing/search, pegasus1.5 for analyze
  * /analyze, /search and /tasks request and response shapes
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


class TwelveLabsClient:
    def __init__(self, api_key: Optional[str] = None, mock: Optional[bool] = None):
        self.api_key = api_key or os.environ.get("TL_API_KEY")
        # Default to mock when no key is present, so the demo never crashes.
        self.mock = (mock if mock is not None else not bool(self.api_key))
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"x-api-key": self.api_key or "", "Content-Type": "application/json"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    # ------------------------------------------------------------------ ingest
    def upload_and_index(self, index_id: str, video_path: str) -> str:
        """
        Submit a video for indexing. Returns a task id. Production code would then
        either poll GET /tasks/{id} or, better, register a webhook on
        index.task.ready so the worker is not blocked on long indexing jobs.
        """
        if self.mock:
            return f"mock-task-{Path(video_path).stem}"
        with open(video_path, "rb") as fh:
            files = {"video_file": fh}
            data = {"index_id": index_id}
            # multipart upload, so we drop the JSON content-type for this call
            resp = httpx.post(
                f"{BASE_URL}/tasks",
                headers={"x-api-key": self.api_key},
                data=data,
                files=files,
                timeout=httpx.Timeout(300.0, connect=10.0),
            )
            resp.raise_for_status()
            return resp.json()["_id"]

    def wait_for_index(self, task_id: str, poll_seconds: int = 5, timeout: int = 1800) -> str:
        """Poll until indexing is ready. Prefer webhooks in production."""
        if self.mock:
            return f"mock-video-{task_id.split('-')[-1]}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self._http.get(f"/tasks/{task_id}")
            resp.raise_for_status()
            body = resp.json()
            status = body.get("status")
            if status == "ready":
                return body["video_id"]
            if status == "failed":
                raise RuntimeError(f"Indexing failed for task {task_id}")
            time.sleep(poll_seconds)
        raise TimeoutError(f"Indexing timed out for task {task_id}")

    # ----------------------------------------------------------------- analyze
    def analyze(
        self,
        video_ref: str,
        prompt: str,
        json_schema: Dict[str, Any],
        model_name: str = "pegasus1.5",
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        """
        Pegasus structured analysis. We pass response_format=json_schema so the
        model returns a machine-readable object instead of prose. We always check
        finish_reason for truncation, because a half-returned JSON object would be
        a silent compliance failure.
        """
        if self.mock:
            return self._mock_analyze(video_ref)
        payload = {
            "model_name": model_name,
            "video": {"asset_id": video_ref},
            "prompt": prompt,
            "temperature": temperature,
            "stream": False,
            "response_format": {"type": "json_schema", "json_schema": json_schema},
        }
        resp = self._http.post("/analyze", json=payload)
        resp.raise_for_status()
        body = resp.json()
        if body.get("finish_reason") == "length":
            raise ValueError("Pegasus response truncated (finish_reason=length); raise max_tokens")
        return json.loads(body["data"]) if isinstance(body["data"], str) else body["data"]

    # ------------------------------------------------------------------ search
    def search(
        self,
        index_id: str,
        query_text: str,
        modalities: List[str],
        page_limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Marengo semantic search. Returns timestamped clips with score and
        confidence. This is our evidence layer: every search hit carries a
        start, end and confidence we can show the reviewer.
        """
        if self.mock:
            return self._mock_search(index_id, query_text, modalities)
        payload = {
            "index_id": index_id,
            "query_text": query_text,
            "search_options": modalities,
            "page_limit": page_limit,
        }
        resp = self._http.post("/search", json=payload)
        resp.raise_for_status()
        return resp.json().get("data", [])

    # -------------------------------------------------------------- mock layer
    def _mock_analyze(self, video_ref: str) -> Dict[str, Any]:
        key = _fixture_key(video_ref)
        path = FIXTURES / "analyze" / f"{key}.json"
        return json.loads(path.read_text())

    def _mock_search(self, index_id: str, query_text: str, modalities: List[str]) -> List[Dict[str, Any]]:
        key = _fixture_key(index_id)
        path = FIXTURES / "search" / f"{key}.json"
        if not path.exists():
            return []
        records = json.loads(path.read_text())
        # Return only clips whose recorded probe query matches this query.
        return [r["hit"] for r in records if r["query"] == query_text]


def _fixture_key(ref: str) -> str:
    """
    Map any reference that contains a scenario name to its fixture key.
    Scenario names are embedded in the mock ids, e.g. mock-video-clean_tutorial.
    """
    for scenario in ("clean_tutorial", "eye_misuse_claim", "mild_profanity", "offbrief_clickbait"):
        if scenario in ref:
            return scenario
    return "clean_tutorial"
