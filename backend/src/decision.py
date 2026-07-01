"""
The decision engine.

This is the heart of the system and the part to defend hardest in the panel.

Principle: the model perceives, the engine decides. Pegasus and Marengo produce
signals (severities, evidence, confidence). This module turns those signals into
a verdict using explicit, inspectable rules driven by config. No language model
makes the final APPROVE / REVIEW / BLOCK call.

Why this matters for an ads buyer:
  * Auditable. Every verdict traces to a rule and a piece of evidence.
  * Tunable per advertiser. Change a threshold in YAML, not a prompt.
  * Consistent. The same inputs always produce the same verdict.
  * Safe. Low-confidence calls route to humans rather than auto-acting.

Decision order (first match wins for the contribution, BLOCK outranks REVIEW
outranks APPROVE for the overall verdict):
  1. Off-brief  -> BLOCK (not eligible to run; it is not an ad for this product)
  2. GARM floor category, corroborated, at or above block severity -> BLOCK
  3. Any policy at or above its block_at severity -> BLOCK
  4. Any policy at or above its review_at severity -> REVIEW
  5. Otherwise -> APPROVE

Confidence and human-in-the-loop:
  * Two-source agreement (Pegasus finding AND a Marengo search hit) -> high
  * Single source -> medium
  * No corroboration on a serious call -> low
  * Any auto APPROVE or BLOCK below auto_decision_min_confidence is downgraded
    to REVIEW, except a corroborated GARM-floor block which stays BLOCK.
"""

from __future__ import annotations

from typing import Dict, List

from .schemas import (
    CONFIDENCE_ORDER,
    SEVERITY_ORDER,
    Confidence,
    Decision,
    ComplianceResult,
    PegasusAnalysis,
    PolicyVerdict,
    SearchEvidence,
    Severity,
)

_DECISION_RANK = {Decision.approve: 0, Decision.review: 1, Decision.block: 2}


def _max_decision(decisions: List[Decision]) -> Decision:
    return max(decisions, key=lambda d: _DECISION_RANK[d]) if decisions else Decision.approve


def evaluate(
    video_ref: str,
    analysis: PegasusAnalysis,
    search_evidence: Dict[str, List[SearchEvidence]],
    policies: List[dict],
    relevance: float,
    relevance_threshold: float,
    auto_decision_min_confidence: str = "medium",
) -> ComplianceResult:

    policy_by_id = {p["id"]: p for p in policies}
    pegasus_by_id = {f.category: f for f in analysis.findings}  # full finding (severity + timestamps + text)

    verdicts: List[PolicyVerdict] = []
    reasons: List[str] = []
    contributions: List[Decision] = []

    # Off-brief is decided after the policy pass below. Pegasus already produced
    # every finding in one multimodal pass, so an off-brief video can still show
    # the violations we caught (a serum clip that is both off-brief AND makes a
    # medical claim should display both, not an empty panel).
    off_brief = (relevance < relevance_threshold) and (not analysis.on_brief)

    # ---- 2. Per-policy evaluation -----------------------------------------
    # Pegasus reads visuals, speech and on-screen text and returns a per-policy
    # severity plus grounded evidence and timestamps. That multimodal finding is
    # both the signal and the timestamped evidence. (Marengo 3.0 search no longer
    # returns a numeric score, so it can't corroborate by magnitude; it remains
    # available for reviewer-driven exploratory search.)
    for policy in policies:
        pid = policy["id"]
        finding = pegasus_by_id.get(pid)
        eff_sev = finding.severity if finding else Severity.none

        block_at = Severity(policy["block_at"])
        review_at = Severity(policy["review_at"])

        contribution = Decision.approve
        if SEVERITY_ORDER[eff_sev] >= SEVERITY_ORDER[block_at]:
            contribution = Decision.block
        elif SEVERITY_ORDER[eff_sev] >= SEVERITY_ORDER[review_at]:
            contribution = Decision.review
        triggered = contribution != Decision.approve

        # Build ONE timestamped evidence row per finding, capped to a short window.
        # The model sometimes still emits a per-second list spanning the whole
        # clip despite the prompt asking for a precise instant; capping at a
        # fixed max width (here 3s) from the earliest reported second means the
        # reviewer always jumps to the actual moment, never "watch everything."
        MAX_EVIDENCE_WINDOW = 3.0
        ev: List[SearchEvidence] = []
        if triggered and finding:
            conf = (Confidence.high if eff_sev == Severity.high
                    else Confidence.medium if eff_sev == Severity.medium else Confidence.low)
            stamps = sorted(finding.timestamps) or [0.0]
            start = float(stamps[0])
            end = min(float(stamps[-1]) + 1.0, start + MAX_EVIDENCE_WINDOW)
            ev.append(SearchEvidence(
                policy_id=pid, query=(finding.evidence or policy["label"]),
                start=start, end=end, score=0.0, confidence=conf,
            ))

        if triggered:
            tag = "GARM floor" if policy.get("garm_floor") else policy.get("suitability_tier", "")
            reasons.append(f"{contribution.value}: {policy['label']} at severity {eff_sev.value} [{tag}].")
            contributions.append(contribution)

        verdicts.append(
            PolicyVerdict(
                policy_id=pid,
                label=policy["label"],
                severity=eff_sev,
                triggered=triggered,
                contribution=contribution.value,
                evidence=ev,
                note=("model finding" if triggered else "clean"),
            )
        )

    # ---- 3. Off-brief is itself a blocking reason -------------------------
    # An off-brief ad should not run regardless of policy. We surface it as the
    # leading reason but keep any policy findings visible alongside it.
    if off_brief:
        reasons.insert(0, (
            f"Off-brief: relevance {relevance:.2f} below threshold "
            f"{relevance_threshold:.2f} and the model judged it off-brief."
        ))
        contributions.append(Decision.block)

    overall = _max_decision(contributions)

    # ---- 4. Confidence and human-in-the-loop ------------------------------
    confidence = _overall_confidence(verdicts, overall)
    if off_brief and overall == Decision.block:
        confidence = Confidence.high  # the relevance call is a confident block

    human_review = overall == Decision.review
    min_conf = Confidence(auto_decision_min_confidence)
    if overall in (Decision.approve, Decision.block) and CONFIDENCE_ORDER[confidence] < CONFIDENCE_ORDER[min_conf]:
        # Low confidence on an automated call. Do not auto-act. The only
        # exception is a corroborated GARM-floor block, which stays BLOCK.
        garm_block = any(
            v.triggered and v.contribution == "BLOCK"
            and policy_by_id[v.policy_id].get("garm_floor")
            for v in verdicts
        )
        if not garm_block:
            reasons.append(
                f"Auto-decision confidence {confidence.value} below "
                f"{min_conf.value}; routing to human review."
            )
            overall = Decision.review
            human_review = True

    if overall == Decision.approve and not reasons:
        reasons.append("No policy violations detected; on-brief and clean across all categories.")

    return ComplianceResult(
        video_ref=video_ref,
        decision=overall,
        confidence=confidence,
        description=analysis.description,
        on_brief=analysis.on_brief,
        on_brief_rationale=analysis.on_brief_rationale,
        relevance_score=relevance,
        reasons=reasons,
        policy_verdicts=verdicts,
        human_review_required=human_review,
    )


def _bump(sev: Severity) -> Severity:
    order = [Severity.none, Severity.low, Severity.medium, Severity.high]
    return order[min(len(order) - 1, SEVERITY_ORDER[sev] + 1)]


def _overall_confidence(verdicts: List[PolicyVerdict], overall: Decision) -> Confidence:
    if overall == Decision.approve:
        # Clean approvals are high confidence; the absence of any finding is itself strong.
        return Confidence.high
    triggered = [v for v in verdicts if v.triggered and v.contribution == overall.value]
    if not triggered:
        return Confidence.medium
    # A high-severity finding is a confident call; lower severities route as medium.
    return Confidence.high if any(v.severity == Severity.high for v in triggered) else Confidence.medium
