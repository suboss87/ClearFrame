# Decision-engine evaluation

Proves the deterministic decision engine behaves as the policy intends, and
catches regressions when thresholds change.

```bash
make eval            # from repo root
# or
python eval/run_eval.py --md REPORT.md   # from backend/
```

## What it measures

`dataset.yaml` is a labeled set of scenarios. Each case fixes a **perception**
(what Pegasus + Marengo reported: findings, severities, corroboration) and the
**intended outcome** a trained reviewer would reach under
[`config/policies.yaml`](../config/policies.yaml). The harness feeds each
perception to the real engine ([`src/decision.py`](../src/decision.py)) and reports:

- per-case PASS / FAIL and a verdict **confusion matrix** (APPROVE / REVIEW / BLOCK),
- **precision / recall / F1** per policy on "should this be flagged?",
- **cost-weighted errors**: *false blocks* (block an approvable ad, hurts the
  advertiser) and *missed flags* (approve a violation, hurts brand safety).

The latest run is checked in at [`REPORT.md`](REPORT.md).

## Scope (be honest about it)

This evaluates the **engine**, holding perception fixed. It does **not** measure
whether the model correctly *sees* a violation, that is a separate layer that
needs a labeled set of real videos. Keeping the two layers separate is the point:
the engine is the deterministic, auditable part, so it gets a deterministic,
100%-or-it-fails gate; perception is probabilistic and evaluated differently.

## Perception smoke test

A first slice of that perception measurement exists here too.
`perception_truth.yaml` holds independently-verified ground truth for the
generated demo videos (what each one actually contains, and where), and
`perception_eval.py` scores the pipeline's real stored results against it:
verdict accuracy, violations caught vs missed, false flags, and whether each
evidence window overlaps the verified truth window.

```bash
python eval/perception_eval.py   # from backend/, against the running API
```

It reads from the running API, changes nothing, and labels itself for what it
is: a smoke test over a handful of scripted videos that catches regressions (a
prompt tweak or a model upgrade that hurts catch rate or timestamp accuracy
shows up immediately), not a statistical benchmark. Grow the truth file to
strengthen it.

## The set has teeth

The cases deliberately probe the subtle rules a naive engine gets wrong: the
off-brief `AND` condition, search corroboration surfacing a finding the narrative
missed, the two-source severity bump, and the GARM floor. Relax any real
threshold and the relevant cases flip to FAIL with a non-zero exit code, so this
doubles as a CI regression gate.

## Extending it

Add a case to `dataset.yaml` (perception + `expect_decision` + `expect_flags`)
and re-run. No code change needed.
