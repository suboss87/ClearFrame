"""
Stage 2: Pegasus reasoning pass.

One /analyze call returns, as structured JSON:
  * the 2 to 5 sentence neutral description (a required deliverable)
  * the on_brief judgement and rationale
  * a list of policy findings with severity, evidence and timestamps

We build the prompt from the policy config so the model is told exactly which
category ids to use and what each one means. The JSON schema (in schemas.py)
constrains the shape. We then validate against the Pydantic model so a malformed
response fails loudly.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .client import TwelveLabsClient
from .schemas import PEGASUS_ANALYZE_SCHEMA, PegasusAnalysis


def build_prompt(policies: List[Dict[str, Any]], brief: str, guidance: str = "") -> str:
    lines = [
        "You are an ad compliance analyst reviewing a creator beauty video that an",
        "advertiser wants to promote as a paid ad. Analyse the full video across",
        "visuals, speech and on-screen text.",
        "",
        "First, write a neutral 2 to 5 sentence description of what happens.",
        "",
        "Second, decide if the video is on-brief for this campaign:",
        f"  CAMPAIGN BRIEF: {brief.strip()}",
        "",
        "Third, assess each of these policy categories. Use the exact category id.",
        "Assign severity none, low, medium or high, and give short evidence with",
        "approximate timestamps in seconds. Only report categories that apply;",
        "use severity none if a category is clearly clean.",
        "",
        "POLICY CATEGORIES:",
    ]
    for p in policies:
        lines.append(f"  - {p['id']}: {p['label']}")
    lines += [
        "",
        "Ground every finding in something actually seen or heard in the video.",
        "Do not invent violations.",
        "",
        "Return ONLY a JSON object — no prose, no markdown, no code fences — with exactly these keys:",
        '  "description": string (2 to 5 sentences),',
        '  "on_brief": boolean,',
        '  "on_brief_rationale": string (one sentence),',
        '  "findings": array of objects, each with:',
        '      "category": one of the policy ids above,',
        '      "severity": one of "none", "low", "medium", "high",',
        '      "evidence": short string grounded in the video,',
        '      "timestamps": array of numbers (seconds into the video).',
        'Use severity "none" or omit a category that is clearly clean. Output JSON only.',
    ]
    if guidance and guidance.strip():
        lines += ["", f"ADVERTISER GUIDANCE: {guidance.strip()}"]
    return "\n".join(lines)


def run_analysis(
    client: TwelveLabsClient,
    video_ref: str,
    policies: List[Dict[str, Any]],
    brief: str,
    guidance: str = "",
) -> PegasusAnalysis:
    prompt = build_prompt(policies, brief, guidance)
    raw = client.analyze(video_ref, prompt=prompt, json_schema=PEGASUS_ANALYZE_SCHEMA)
    # Validate the model output against our contract. If Pegasus returns a
    # severity outside the enum or drops a required field, this raises here
    # rather than corrupting the decision downstream.
    return PegasusAnalysis(**raw)
