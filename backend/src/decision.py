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
    pegasus_by_id: Dict[str, Severity] = {f.category: f.severity for f in analysis.findings}

    verdicts: List[PolicyVerdict] = []
    reasons: List[str] = []
    contributions: List[Decision] = []

    # ---- 1. Off-brief gate -------------------------------------------------
    off_brief = (relevance < relevance_threshold) and (not analysis.on_brief)
    if off_brief:
        reasons.append(
            f"Off-brief: relevance {relevance:.2f} below threshold "
            f"{relevance_threshold:.2f} and the model judged it off-brief."
        )
        return ComplianceResult(
            video_ref=video_ref,
            decision=Decision.block,
            confidence=Confidence.high,
            description=analysis.description,
            on_brief=False,
            relevance_score=relevance,
            reasons=reasons,
            policy_verdicts=[],
            human_review_required=False,
        )

    # ---- 2. Per-policy evaluation -----------------------------------------
    for policy in policies:
        pid = policy["id"]
        peg_sev = pegasus_by_id.get(pid, Severity.none)
        evidence = search_evidence.get(pid, [])
        corroborated = len(evidence) > 0

        # Effective severity: search corroboration can lift a model finding by
        # one notch, because two independent signals are stronger than one.
        eff_sev = peg_sev
        if corroborated and SEVERITY_ORDER[peg_sev] < SEVERITY_ORDER[Severity.high]:
            top_conf = max((e.confidence for e in evidence), key=lambda c: CONFIDENCE_ORDER[c])
            if top_conf == Confidence.high and peg_sev != Severity.none:
                eff_sev = _bump(peg_sev)
            # A high-confidence search hit with no model finding still counts as low.
            if peg_sev == Severity.none and top_conf in (Confidence.medium, Confidence.high):
                eff_sev = Severity.low

        block_at = Severity(policy["block_at"])
        review_at = Severity(policy["review_at"])

        contribution = Decision.approve
        if SEVERITY_ORDER[eff_sev] >= SEVERITY_ORDER[block_at]:
            contribution = Decision.block
        elif SEVERITY_ORDER[eff_sev] >= SEVERITY_ORDER[review_at]:
            contribution = Decision.review

        triggered = contribution != Decision.approve
        if triggered:
            tag = "GARM floor" if policy.get("garm_floor") else policy.get("suitability_tier", "")
            note = f"{policy['label']} at severity {eff_sev.value}"
            if corroborated:
                note += f", corroborated by {len(evidence)} search hit(s)"
            reasons.append(f"{contribution.value}: {note} [{tag}].")
            contributions.append(contribution)

        verdicts.append(
            PolicyVerdict(
                policy_id=pid,
                label=policy["label"],
                severity=eff_sev,
                triggered=triggered,
                contribution=contribution.value,
                evidence=evidence,
                note=("corroborated" if corroborated else "model only") if triggered else "clean",
            )
        )

    overall = _max_decision(contributions)

    # ---- 3. Confidence and human-in-the-loop ------------------------------
    confidence = _overall_confidence(verdicts, overall)

    human_review = overall == Decision.review
    min_conf = Confidence(auto_decision_min_confidence)
    if overall in (Decision.approve, Decision.block) and CONFIDENCE_ORDER[confidence] < CONFIDENCE_ORDER[min_conf]:
        # Low confidence on an automated call. Do not auto-act. The only
        # exception is a corroborated GARM-floor block, which stays BLOCK.
        garm_block = any(
            v.triggered and v.contribution == "BLOCK"
            and policy_by_id[v.policy_id].get("garm_floor")
            and v.note == "corroborated"
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
    corroborated = any(v.note == "corroborated" for v in triggered)
    return Confidence.high if corroborated else Confidence.medium
