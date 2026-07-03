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


def build_prompt(policies: List[Dict[str, Any]], brief: str, guidance: str = "",
                 duration_s: float = None) -> str:
    lines = [
        "You are an ad compliance analyst reviewing a creator beauty video that an",
        "advertiser wants to promote as a paid ad. Analyse the full video across",
        "visuals, speech and on-screen text.",
    ]
    if duration_s:
        lines.append(f"The video is {duration_s:.0f} seconds long. Every timestamp you report "
                     f"MUST be between 0 and {duration_s:.0f}.")
    lines += [
        "",
        "First, write a neutral 2 to 5 sentence description of what happens.",
        "",
        "Second, decide if the video is on-brief for this campaign:",
        f"  CAMPAIGN BRIEF: {brief.strip()}",
        "",
        "Third, check the video against these policy categories and report ONLY",
        "actual violations. Use the exact category id.",
        "",
        "STRICT RULES for findings:",
        "  - Include a category ONLY if you actually observed a violation of it.",
        "  - If a category is clean, OMIT it entirely. Do NOT add it to confirm it",
        "    is fine, and never use severity none/low just to say it is compliant.",
        "  - The evidence must describe the violation you saw or heard. NEVER write",
        "    evidence about the absence of a problem (e.g. 'no indication of...',",
        "    'there is no...', 'does not show...'). If you would write that, omit it.",
        "  - Severity: low = a brief or minor real violation; medium = a clear",
        "    violation; high = severe or repeated. Normal, safe product use on the",
        "    face is NOT a violation.",
        "  - Give one short evidence string per violation with the timestamp(s) in",
        "    seconds where it occurs.",
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
        "Return ONLY a JSON object (no prose, no markdown, no code fences) with exactly these keys:",
        '  "description": string (2 to 5 sentences),',
        '  "on_brief": boolean,',
        '  "on_brief_rationale": string, 8 WORDS OR FEWER. A complete short phrase',
        '      naming the concrete fact that decided it, e.g. "Ora lipstick applied',
        '      and named on camera" or "No campaign product shown or mentioned".',
        '      Never a sentence fragment or a clause cut off mid-thought - it must',
        '      read as a finished thought on its own, just a short one.',
        '  "relevance_score": number 0 to 1 (how strongly the video matches the campaign brief; 1 = clearly on-brief and about the product, 0 = unrelated),',
        '  "findings": array of objects, each with:',
        '      "category": one of the policy ids above,',
        '      "severity": one of "none", "low", "medium", "high",',
        '      "evidence": a SHORT phrase, under 12 words, naming specifically what was',
        '          seen, heard, or read. If it is speech or on-screen text, quote ONLY',
        '          the offending word or short phrase itself (e.g. "damn"), NOT the full',
        '          sentence or narration around it. Do not describe the surrounding scene',
        '          here, that belongs in the description field, not the evidence.',
        '      "timestamps": array of 1 to 3 numbers (seconds, integer or one decimal',
        '          place, e.g. 7 or 7.5). This is a precise second-based reading, not a',
        '          rough guess: watch or listen again and report the exact second the',
        '          violation BEGINS - the second the unsafe action starts, the word is',
        '          spoken, or the on-screen text becomes visible. If the offending word is',
        '          spoken partway through a longer sentence, the timestamp is the second',
        '          THAT WORD is spoken, never the second the sentence starts. Give ONE',
        '          number per DISTINCT moment the violation is seen or heard: if the same',
        '          violation happens at two separate points (e.g. a swear at 2s and again',
        '          at 7s), give both seconds, each as precise as the first. NOT a range',
        '          spanning the whole clip, and never a list of every second the video plays;',
        '          pinpoint the exact onset second of each moment, do not describe the',
        '          duration.',
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
    duration_s: float = None,
) -> PegasusAnalysis:
    prompt = build_prompt(policies, brief, guidance, duration_s=duration_s)
    raw = client.analyze(video_ref, prompt=prompt, json_schema=PEGASUS_ANALYZE_SCHEMA)
    # Validate the model output against our contract. If Pegasus returns a
    # severity outside the enum or drops a required field, this raises here
    # rather than corrupting the decision downstream.
    analysis = PegasusAnalysis(**raw)
    # The model still occasionally reports a second at or past the end of the
    # clip (seen live: start 10.0 on a 10.005s video, which seeks the player to
    # the final frame and looks broken). Clamp every timestamp into the real
    # runway so the evidence window always lands on playable video.
    if duration_s and duration_s > 1.0:
        ceiling = duration_s - 1.0
        for f in analysis.findings:
            f.timestamps = [max(0.0, min(float(t), ceiling)) for t in f.timestamps]
    return analysis
