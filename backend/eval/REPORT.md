# ClearFrame — decision-engine evaluation

**16/16 cases pass — 100% verdict accuracy.** Measures the deterministic decision engine against a labeled set of intended compliance outcomes, holding model perception fixed.

## Per-case

| case | truth | predicted | result |
|---|---|---|---|
| `clean_tutorial` | APPROVE | APPROVE | ✅ |
| `clean_puffery` | APPROVE | APPROVE | ✅ |
| `onbrief_low_relevance_score` | APPROVE | APPROVE | ✅ |
| `high_relevance_clean` | APPROVE | APPROVE | ✅ |
| `mild_profanity` | REVIEW | REVIEW | ✅ |
| `drug_reference_passing` | REVIEW | REVIEW | ✅ |
| `subtle_unsafe_usage` | REVIEW | REVIEW | ✅ |
| `multi_minor_review` | REVIEW | REVIEW | ✅ |
| `eye_misuse_claim` | BLOCK | BLOCK | ✅ |
| `offbrief_clickbait` | BLOCK | BLOCK | ✅ |
| `offbrief_confirmed` | BLOCK | BLOCK | ✅ |
| `hate_speech_garm` | BLOCK | BLOCK | ✅ |
| `drug_use_blatant` | BLOCK | BLOCK | ✅ |
| `strong_profanity` | BLOCK | BLOCK | ✅ |
| `profanity_moderate` | REVIEW | REVIEW | ✅ |
| `medical_claim_block` | BLOCK | BLOCK | ✅ |

## Verdict confusion matrix

Rows = ground truth, columns = predicted.

| truth ＼ pred | APPROVE | REVIEW | BLOCK |
|---|---|---|---|
| **APPROVE** | 4 | 0 | 0 |
| **REVIEW** | 0 | 5 | 0 |
| **BLOCK** | 0 | 0 | 7 |

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

_Scope: this evaluates the deterministic decision engine, holding model perception fixed. Whether the model correctly perceives a violation is a separate layer requiring labeled real videos._
