#!/usr/bin/env python3
"""
ClearFrame decision-engine evaluation harness.

Runs every labeled case in dataset.yaml through the real, deterministic decision
engine (src/decision.py) and reports how well the engine's verdicts match the
intended compliance outcomes:

  * per-case PASS / FAIL
  * verdict confusion matrix (APPROVE / REVIEW / BLOCK)
  * per-policy precision / recall / F1 on "should this policy be flagged?"
  * cost-weighted errors: false blocks (hurt the advertiser) and missed
    violations (hurt brand safety) — the two failures that actually matter

What it measures: the engine, holding perception fixed. It does NOT measure
whether the model correctly *sees* a violation — that needs labeled real videos
and is a separate layer.

Usage:
    python eval/run_eval.py                  # human-readable report
    python eval/run_eval.py --md REPORT.md   # also write a markdown report

Exit code is 0 only if every case passes (so CI can gate on it).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Make `src` importable when run as `python eval/run_eval.py` from backend/.
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from src.decision import evaluate  # noqa: E402
from src.schemas import (  # noqa: E402
    PegasusAnalysis,
    PegasusFinding,
    Severity,
)

DATASET = Path(__file__).resolve().parent / "dataset.yaml"
POLICIES = BACKEND / "config" / "policies.yaml"
VERDICTS = ["APPROVE", "REVIEW", "BLOCK"]


def load_policies() -> tuple[list, float, str]:
    cfg = yaml.safe_load(POLICIES.read_text())
    return cfg["policies"], cfg["relevance_threshold"], cfg["auto_decision_min_confidence"]


def build_analysis(case: dict) -> PegasusAnalysis:
    findings = [
        PegasusFinding(category=pid, severity=Severity(sev), evidence="", timestamps=[])
        for pid, sev in (case.get("findings") or {}).items()
    ]
    return PegasusAnalysis(
        description=case.get("note", ""),
        on_brief=case["on_brief"],
        on_brief_rationale="",
        findings=findings,
    )


def run() -> dict:
    policies, rel_threshold, min_conf = load_policies()
    policy_ids = [p["id"] for p in policies]
    cases = yaml.safe_load(DATASET.read_text())["cases"]

    rows = []
    confusion = {a: {p: 0 for p in VERDICTS} for a in VERDICTS}  # confusion[truth][pred]
    # Per-policy flag counters for precision/recall.
    tp = {p: 0 for p in policy_ids}
    fp = {p: 0 for p in policy_ids}
    fn = {p: 0 for p in policy_ids}
    false_blocks = []      # predicted BLOCK, truth APPROVE — costs the advertiser
    missed_violations = []  # predicted APPROVE, truth REVIEW/BLOCK — costs brand safety

    for c in cases:
        result = evaluate(
            video_ref=c["id"],
            analysis=build_analysis(c),
            policies=policies,
            relevance=c["relevance"],
            relevance_threshold=rel_threshold,
            auto_decision_min_confidence=min_conf,
        )
        pred = result.decision.value
        truth = c["expect_decision"]
        pred_flags = {v.policy_id for v in result.policy_verdicts if v.triggered}
        truth_flags = set(c.get("expect_flags") or [])

        ok = (pred == truth) and (pred_flags == truth_flags)
        rows.append({
            "id": c["id"], "truth": truth, "pred": pred,
            "truth_flags": sorted(truth_flags), "pred_flags": sorted(pred_flags),
            "conf": result.confidence.value, "ok": ok,
        })

        confusion[truth][pred] += 1
        for pid in policy_ids:
            in_pred, in_truth = pid in pred_flags, pid in truth_flags
            if in_pred and in_truth:
                tp[pid] += 1
            elif in_pred and not in_truth:
                fp[pid] += 1
            elif in_truth and not in_pred:
                fn[pid] += 1
        if pred == "BLOCK" and truth == "APPROVE":
            false_blocks.append(c["id"])
        if pred == "APPROVE" and truth in ("REVIEW", "BLOCK"):
            missed_violations.append(c["id"])

    def prf(pid):
        t, f, n = tp[pid], fp[pid], fn[pid]
        precision = t / (t + f) if (t + f) else 1.0
        recall = t / (t + n) if (t + n) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        return precision, recall, f1

    per_policy = {pid: prf(pid) for pid in policy_ids}
    passed = sum(r["ok"] for r in rows)
    macro = [prf(pid) for pid in policy_ids]
    return {
        "rows": rows, "confusion": confusion, "per_policy": per_policy,
        "tp": tp, "fp": fp, "fn": fn, "policy_ids": policy_ids,
        "passed": passed, "total": len(rows),
        "accuracy": passed / len(rows) if rows else 0.0,
        "false_blocks": false_blocks, "missed_violations": missed_violations,
        "macro_precision": sum(m[0] for m in macro) / len(macro) if macro else 0.0,
        "macro_recall": sum(m[1] for m in macro) / len(macro) if macro else 0.0,
        "macro_f1": sum(m[2] for m in macro) / len(macro) if macro else 0.0,
    }


# ---------------------------------------------------------------- rendering
def render(res: dict) -> str:
    L = []
    L.append("ClearFrame: decision-engine evaluation")
    L.append("=" * 64)
    L.append(f"Cases: {res['total']}   Passed: {res['passed']}   "
             f"Verdict accuracy: {res['accuracy'] * 100:.1f}%")
    L.append("")

    L.append("Per-case")
    L.append("-" * 64)
    L.append(f"{'case':<34}{'truth':<9}{'pred':<9}{'':<3}")
    for r in res["rows"]:
        mark = "PASS" if r["ok"] else "FAIL"
        line = f"{r['id']:<34}{r['truth']:<9}{r['pred']:<9}{mark}"
        if not r["ok"]:
            line += f"  exp_flags={r['truth_flags']} got={r['pred_flags']}"
        L.append(line)
    L.append("")

    L.append("Verdict confusion matrix  (rows = truth, cols = predicted)")
    L.append("-" * 64)
    L.append(f"{'':<10}" + "".join(f"{p:>9}" for p in VERDICTS))
    for truth in VERDICTS:
        L.append(f"{truth:<10}" + "".join(f"{res['confusion'][truth][p]:>9}" for p in VERDICTS))
    L.append("")

    L.append("Per-policy flag detection")
    L.append("-" * 64)
    L.append(f"{'policy':<20}{'prec':>8}{'recall':>8}{'f1':>8}{'tp':>5}{'fp':>5}{'fn':>5}")
    for pid in res["policy_ids"]:
        p, r, f1 = res["per_policy"][pid]
        L.append(f"{pid:<20}{p:>8.2f}{r:>8.2f}{f1:>8.2f}"
                 f"{res['tp'][pid]:>5}{res['fp'][pid]:>5}{res['fn'][pid]:>5}")
    L.append(f"{'macro avg':<20}{res['macro_precision']:>8.2f}"
             f"{res['macro_recall']:>8.2f}{res['macro_f1']:>8.2f}")
    L.append("")

    L.append("Cost-weighted errors (the ones that matter)")
    L.append("-" * 64)
    fb, mv = res["false_blocks"], res["missed_violations"]
    L.append(f"False blocks    (BLOCK an approvable ad, hurts advertiser): {len(fb)} {fb or ''}")
    L.append(f"Missed flags    (APPROVE a violation, hurts brand safety): {len(mv)} {mv or ''}")
    L.append("")
    L.append("Scope: measures the deterministic decision engine, holding model")
    L.append("perception fixed. Perception accuracy is a separate layer.")
    return "\n".join(L)


def render_md(res: dict) -> str:
    L = []
    L.append("# ClearFrame: decision-engine evaluation\n")
    L.append(f"**{res['passed']}/{res['total']} cases pass, "
             f"{res['accuracy'] * 100:.0f}% verdict accuracy.** "
             "Measures the deterministic decision engine against a labeled set of "
             "intended compliance outcomes, holding model perception fixed.\n")

    L.append("## Per-case\n")
    L.append("| case | truth | predicted | result |")
    L.append("|---|---|---|---|")
    for r in res["rows"]:
        L.append(f"| `{r['id']}` | {r['truth']} | {r['pred']} | "
                 f"{'✅' if r['ok'] else '❌'} |")

    L.append("\n## Verdict confusion matrix\n")
    L.append("Rows = ground truth, columns = predicted.\n")
    L.append("| truth ＼ pred | " + " | ".join(VERDICTS) + " |")
    L.append("|---|" + "---|" * len(VERDICTS))
    for truth in VERDICTS:
        L.append(f"| **{truth}** | " + " | ".join(str(res["confusion"][truth][p]) for p in VERDICTS) + " |")

    L.append("\n## Per-policy flag detection\n")
    L.append("| policy | precision | recall | F1 | TP | FP | FN |")
    L.append("|---|---|---|---|---|---|---|")
    for pid in res["policy_ids"]:
        p, r, f1 = res["per_policy"][pid]
        L.append(f"| `{pid}` | {p:.2f} | {r:.2f} | {f1:.2f} | "
                 f"{res['tp'][pid]} | {res['fp'][pid]} | {res['fn'][pid]} |")
    L.append(f"| **macro avg** | {res['macro_precision']:.2f} | "
             f"{res['macro_recall']:.2f} | {res['macro_f1']:.2f} | | | |")

    fb, mv = res["false_blocks"], res["missed_violations"]
    L.append("\n## Cost-weighted errors\n")
    L.append(f"- **False blocks** (BLOCK an approvable ad, hurts the advertiser): "
             f"**{len(fb)}** {', '.join(f'`{x}`' for x in fb)}")
    L.append(f"- **Missed flags** (APPROVE a real violation, hurts brand safety): "
             f"**{len(mv)}** {', '.join(f'`{x}`' for x in mv)}")
    L.append("\n_Scope: this evaluates the deterministic decision engine, holding "
             "model perception fixed. Whether the model correctly perceives a "
             "violation is a separate layer requiring labeled real videos._")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", metavar="PATH", help="also write a markdown report")
    args = ap.parse_args()

    res = run()
    print(render(res))
    if args.md:
        out = Path(args.md)
        if not out.is_absolute():
            out = Path(__file__).resolve().parent / out
        out.write_text(render_md(res))
        print(f"\nMarkdown report written to {out}")

    sys.exit(0 if res["passed"] == res["total"] else 1)


if __name__ == "__main__":
    main()
