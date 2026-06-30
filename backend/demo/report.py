"""
Generates a self-contained HTML evidence report for the reviewed videos.

This is the artefact a human reviewer or an advertiser would actually look at:
one card per video, the decision badge, the auto-generated description, the
reasons, and the timestamped evidence per policy. No framework, just a string,
so it opens anywhere.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import List, Tuple

from src.schemas import Decision, ComplianceResult

_BADGE_CLASS = {Decision.approve: "approve", Decision.review: "review", Decision.block: "block"}


def write_report(cfg: dict, results: List[Tuple[str, ComplianceResult]]) -> str:
    cards = "\n".join(_card(label, r) for label, r in results)
    html = _TEMPLATE.format(
        advertiser=escape(cfg["policies"]["advertiser"]),
        campaign=escape(cfg["policies"]["campaign"]),
        cards=cards,
    )
    out = Path(__file__).resolve().parent / "report.html"
    out.write_text(html)
    return str(out)


def _card(label: str, r: ComplianceResult) -> str:
    reasons = "".join(f"<li>{escape(x)}</li>" for x in r.reasons)
    evidence_rows = ""
    for v in r.policy_verdicts:
        if not v.triggered:
            continue
        if v.evidence:
            for e in v.evidence:
                evidence_rows += (
                    f"<tr><td>{escape(v.policy_id)}</td>"
                    f"<td>{e.start:.1f}s - {e.end:.1f}s</td>"
                    f"<td>{escape(e.confidence.value)}</td>"
                    f"<td>{escape(e.query)}</td></tr>"
                )
        else:
            evidence_rows += (
                f"<tr><td>{escape(v.policy_id)}</td><td>model reasoning</td>"
                f"<td>{escape(v.severity.value)}</td><td>flagged without search corroboration</td></tr>"
            )
    evidence = (
        f"<table><tr><th>policy</th><th>timestamp</th><th>confidence</th><th>signal</th></tr>{evidence_rows}</table>"
        if evidence_rows else "<p class='clean'>No violations. Clean across all policy categories.</p>"
    )
    badge = _BADGE_CLASS[r.decision]
    hil = " &middot; human review queued" if r.human_review_required else ""
    return f"""
    <div class="card">
      <div class="head">
        <span class="badge {badge}">{r.decision.value}</span>
        <span class="file">{escape(r.video_ref)}</span>
        <span class="label">{escape(label)}</span>
      </div>
      <div class="meta">confidence {escape(r.confidence.value)} &middot; on-brief {r.on_brief}
        &middot; relevance {r.relevance_score:.2f}{hil}</div>
      <p class="desc">{escape(r.description)}</p>
      <div class="why"><strong>Why</strong><ul>{reasons}</ul></div>
      {evidence}
    </div>
    """


_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>ClearFrame evidence report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#0f1117; color:#e8eaed; margin:0; padding:32px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:#9aa0a6; margin-bottom:24px; }}
  .card {{ background:#1a1d27; border:1px solid #2a2e3a; border-radius:12px; padding:20px; margin-bottom:18px; }}
  .head {{ display:flex; align-items:center; gap:12px; margin-bottom:8px; }}
  .file {{ font-weight:600; }}
  .label {{ color:#9aa0a6; font-size:13px; }}
  .badge {{ font-weight:700; font-size:12px; padding:4px 10px; border-radius:6px; letter-spacing:.5px; }}
  .badge.approve {{ background:#11331f; color:#5ee08a; }}
  .badge.review  {{ background:#3a3210; color:#f2cd57; }}
  .badge.block   {{ background:#3a1414; color:#ff7b72; }}
  .meta {{ color:#9aa0a6; font-size:13px; margin-bottom:10px; }}
  .desc {{ line-height:1.5; }}
  .why ul {{ margin:6px 0 14px; padding-left:18px; }}
  .why li {{ margin:3px 0; color:#cdd1d6; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid #2a2e3a; }}
  th {{ color:#9aa0a6; font-weight:600; }}
  .clean {{ color:#5ee08a; }}
</style></head>
<body>
  <h1>ClearFrame ad compliance report</h1>
  <div class="sub">{advertiser} &middot; {campaign}</div>
  {cards}
</body></html>
"""
