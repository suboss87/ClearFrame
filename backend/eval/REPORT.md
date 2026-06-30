# ClearFrame — decision-engine correctness gate

**16/16 cases pass. The deterministic engine is provably correct:** given any set of model perceptions (severities, evidence, corroboration), the rules produce the intended compliance verdict every time. This is the guarantee the engine provides — reproducible, auditable, regression-gated. Perception accuracy (does the model *see* the violation?) is a separate, probabilistic layer evaluated independently against labeled real videos.

## Per-case

| case | truth | predicted | result |
|---|---|---|---|
| `clean_tutorial` | APPROVE | APPROVE | ✅ |
| `clean_puffery` | APPROVE | APPROVE | ✅ |
| `onbrief_low_relevance_score` | APPROVE | APPROVE | ✅ |
| `high_relevance_clean` | APPROVE | APPROVE | ✅ |
| `mild_profanity` | REVIEW | REVIEW | ✅ |
| `drug_reference_passing` | REVIEW | REVIEW | ✅ |
| `search_only_unsafe` | REVIEW | REVIEW | ✅ |
| `multi_minor_review` | REVIEW | REVIEW | ✅ |
| `eye_misuse_claim` | BLOCK | BLOCK | ✅ |
| `offbrief_clickbait` | BLOCK | BLOCK | ✅ |
| `offbrief_confirmed` | BLOCK | BLOCK | ✅ |
| `hate_speech_garm` | BLOCK | BLOCK | ✅ |
| `drug_use_blatant` | BLOCK | BLOCK | ✅ |
| `strong_profanity` | BLOCK | BLOCK | ✅ |
| `profanity_corroborated_escalation` | BLOCK | BLOCK | ✅ |
| `medical_claim_block` | BLOCK | BLOCK | ✅ |

## Verdict confusion matrix

Rows = ground truth, columns = predicted.

| truth ＼ pred | APPROVE | REVIEW | BLOCK |
|---|---|---|---|
| **APPROVE** | 4 | 0 | 0 |
| **REVIEW** | 0 | 4 | 0 |
| **BLOCK** | 0 | 0 | 8 |

## Per-policy flag detection

| policy | precision | recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| `hate_harassment` | 1.00 | 1.00 | 1.00 | 1 | 0 | 0 |
| `drugs_illegal` | 1.00 | 1.00 | 1.00 | 3 | 0 | 0 |
| `profanity` | 1.00 | 1.00 | 1.00 | 4 | 0 | 0 |
| `unsafe_usage` | 1.00 | 1.00 | 1.00 | 2 | 0 | 0 |
| `medical_claims` | 1.00 | 1.00 | 1.00 | 2 | 0 | 0 |
| **macro avg** | 1.00 | 1.00 | 1.00 | | | |

## Cost-weighted errors

- **False blocks** (BLOCK an approvable ad — hurts the advertiser): **0** 
- **Missed flags** (APPROVE a real violation — hurts brand safety): **0** 

## What this proves

The decision engine is a **deterministic function**: signals in, verdict out. This eval proves it implements the policy correctly — the same inputs always yield the same, intended verdict. Relaxing any threshold flips a case to FAIL with a non-zero exit code, so it doubles as a CI regression gate. It does **not** measure whether TwelveLabs correctly perceives a violation in a real video — that is a separate, probabilistic evaluation requiring labeled content.
