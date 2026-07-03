"""
The decision engine.

This is the heart of the system and the design decision to defend hardest.

Principle: the model perceives, the engine decides. Pegasus reads the video and
returns findings (severities, evidence, timestamps). This module turns those
findings into a verdict using explicit, inspectable rules driven by config. No
language model makes the final APPROVE / REVIEW / BLOCK call.

Why this matters for an ads buyer:
  * Auditable. Every verdict traces to a rule and a piece of evidence.
  * Tunable per advertiser. Change a threshold in YAML, not a prompt.
  * Consistent. The same inputs always produce the same verdict.
  * Safe. Low-confidence calls route to humans rather than auto-acting.

Decision order (BLOCK outranks REVIEW outranks APPROVE for the overall verdict):
  1. Off-brief  -> BLOCK (not eligible to run; it is not an ad for this product)
  2. Any policy at or above its block_at severity -> BLOCK
  3. Any policy at or above its review_at severity -> REVIEW
  4. Otherwise -> APPROVE
GARM floor (hate/harassment, drugs/illegal) is not a separate step above, it goes
through the same per-policy check as every other category. Its one distinct
effect is below: a low-confidence GARM-floor block is never downgraded.

Confidence and human-in-the-loop:
  * A clean APPROVE (no findings at all) -> high; the absence of any finding is
    itself a strong signal.
  * A high-severity finding driving the verdict -> high; anything less -> medium.
  * Any auto APPROVE or BLOCK below auto_decision_min_confidence is downgraded
    to REVIEW, except a GARM-floor block, which stays BLOCK regardless.
"""

from __future__ import annotations

from typing import List

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
    policies: List[dict],
    relevance: float,
    relevance_threshold: float,
    auto_decision_min_confidence: str = "medium",
    duration_s: float = None,
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

        # Build evidence rows from the finding's timestamps. Timestamps within
        # MAX_EVIDENCE_WINDOW of each other are one moment (the model
        # describing a continuous violation), so they merge into one row;
        # timestamps farther apart are DISTINCT moments of the same violation
        # (a swear at 1s and again at 7s) and each gets its own clickable row.
        #
        # Each row gets EVIDENCE_PAD seconds of lead-in and lead-out around the
        # reported timestamp(s), not just trailing padding - the model's
        # second is an estimate, not a frame-exact cut point, so a reviewer
        # clicking the row should land slightly BEFORE the moment and see it
        # play through slightly AFTER, not have it already happened when
        # playback starts. Clamped to the clip's real runway when known so a
        # timestamp near 0 or near the end never seeks outside the video.
        MAX_EVIDENCE_WINDOW = 3.0
        EVIDENCE_PAD = 1.0
        ev: List[SearchEvidence] = []
        if triggered and finding:
            conf = (Confidence.high if eff_sev == Severity.high
                    else Confidence.medium if eff_sev == Severity.medium else Confidence.low)
            if getattr(finding, "spans", None):
                # Marengo MEASURED these clip boundaries for this finding's
                # evidence text (see pipeline.refine_timestamps). A measured
                # segment is guaranteed to contain the violation, unlike a
                # padded window around the model's estimated second - which
                # can miss entirely when the offending word sits later in a
                # sentence than the model guessed. Small symmetric pad so the
                # reviewer gets lead-in/lead-out around the measurement.
                for s, e in sorted(finding.spans):
                    start = max(0.0, float(s) - 0.5)
                    end = float(e) + 0.5
                    if duration_s:
                        end = min(end, duration_s)
                        start = min(start, end)
                    ev.append(SearchEvidence(
                        policy_id=pid, query=(finding.evidence or policy["label"]),
                        start=start, end=end, confidence=conf,
                    ))
            else:
                stamps = sorted(float(t) for t in finding.timestamps) or [0.0]
                clusters: List[List[float]] = [[stamps[0]]]
                for t in stamps[1:]:
                    if t - clusters[-1][-1] <= MAX_EVIDENCE_WINDOW:
                        clusters[-1].append(t)
                    else:
                        clusters.append([t])
                for cluster in clusters:
                    start = max(0.0, cluster[0] - EVIDENCE_PAD)
                    end = cluster[-1] + EVIDENCE_PAD
                    if duration_s:
                        end = min(end, duration_s)
                        start = min(start, end)
                    ev.append(SearchEvidence(
                        policy_id=pid, query=(finding.evidence or policy["label"]),
                        start=start, end=end, confidence=conf,
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
        # exception is a GARM-floor block, which stays BLOCK regardless.
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


def _overall_confidence(verdicts: List[PolicyVerdict], overall: Decision) -> Confidence:
    if overall == Decision.approve:
        # Clean approvals are high confidence; the absence of any finding is itself strong.
        return Confidence.high
    triggered = [v for v in verdicts if v.triggered and v.contribution == overall.value]
    if not triggered:
        return Confidence.medium
    # A high-severity finding is a confident call; lower severities route as medium.
    return Confidence.high if any(v.severity == Severity.high for v in triggered) else Confidence.medium
