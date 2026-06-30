# Decision-engine correctness gate

Proves the deterministic decision engine is **provably correct**: given fixed
perceptions, the rules always produce the intended compliance verdict. This is a
mathematical guarantee on the engine layer — the auditable, reproducible,
regression-gated part of the system. Perception accuracy (does the model *see*
the violation?) is a separate, probabilistic layer that requires labeled real
videos and is evaluated independently.

```bash
make eval            # from repo root
# or
python eval/run_eval.py --md REPORT.md   # from backend/
```

## What it measures

`dataset.yaml` is a labeled set of scenarios. Each case fixes a **perception**
(what Pegasus + Marengo reported — findings, severities, corroboration) and the
**intended outcome** a trained reviewer would reach under
[`config/policies.yaml`](../config/policies.yaml). The harness feeds each
perception to the real engine ([`src/decision.py`](../src/decision.py)) and reports:

- per-case PASS / FAIL and a verdict **confusion matrix** (APPROVE / REVIEW / BLOCK),
- **precision / recall / F1** per policy on "should this be flagged?",
- **cost-weighted errors** — *false blocks* (block an approvable ad, hurts the
  advertiser) and *missed flags* (approve a violation, hurts brand safety).

The latest run is checked in at [`REPORT.md`](REPORT.md).

## Why this matters

In an ads system a wrong auto-block on a large advertiser is a revenue incident.
This eval guarantees that, for any perception the models produce, the engine maps
it to the correct compliance decision. It is the auditable part: a regulator, an
advertiser, or an internal review can inspect the rules and verify the mapping
without reasoning about model uncertainty.

## Scope (stated plainly)

This evaluates the **engine**, holding perception fixed. It does **not** measure
whether the model correctly *sees* a violation — that is a separate layer that
needs a labeled set of real videos. Keeping the two layers separate is the point:
the engine is the deterministic, auditable part, so it gets a deterministic,
all-pass-or-fail gate; perception is probabilistic and evaluated differently
(precision/recall against labeled real videos, tracked separately).

## The set has teeth

The cases deliberately probe the subtle rules a naive engine gets wrong: the
off-brief `AND` condition, search corroboration surfacing a finding the narrative
missed, the two-source severity bump, and the GARM floor. Relax any real
threshold and the relevant cases flip to FAIL with a non-zero exit code, so this
doubles as a CI regression gate.

## Extending it

Add a case to `dataset.yaml` (perception + `expect_decision` + `expect_flags`)
and re-run. No code change needed.
