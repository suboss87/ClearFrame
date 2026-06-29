# Greenlight

Brand-safe greenlighting for creator video ads.

Greenlight is an automated ad compliance gate for a social platform that promotes
creator beauty videos as paid ads. For every submitted creative it returns an
**APPROVE / REVIEW / BLOCK** decision, an auto-generated 2 to 5 sentence
description, and **timestamped evidence** for every reason behind the call. It
uses TwelveLabs for video perception and a deterministic policy engine for the
verdict.

## The one idea

> The model perceives. The engine decides.

TwelveLabs (Pegasus and Marengo) handles what is genuinely hard: understanding
what happens in a video across visuals, speech and on-screen text. A separate,
deterministic policy engine turns those perceptions into the verdict. No language
model makes the final compliance call on its own.

This split is deliberate. In an ads system a wrong auto-block on a large
advertiser is a revenue and trust incident. Keeping the decision in inspectable
rules makes it auditable, tunable per advertiser, consistent, and safe to operate.

## Pipeline

```
  submit creative
        |
        v
  [0] ingest + index            TwelveLabs /tasks  (async; webhook in prod)
        |
        v
  [1] relevance gate            Marengo /search vs the campaign brief
        |                       off-brief  ->  BLOCK early, save compute
        v
  [2] reasoning pass            Pegasus /analyze with a JSON schema
        |                       -> description, on-brief, structured findings
        v
  [3] evidence pass             Marengo /search per-policy probes
        |                       -> timestamped, confidence-scored clips
        v
  [4] decision engine           deterministic rules over [1][2][3]
        |                       -> APPROVE / REVIEW / BLOCK + reasons + evidence
        v
   GreenlightResult  ->  HTML report  /  review queue
```

Two perception passes, one decision. The reasoning pass (Pegasus) gives an
open-ended read and catches novel issues. The evidence pass (Marengo) corroborates
specific known-bad patterns with timestamped clips. The most serious calls require
both to agree, which is the core trust mechanism.

## Why two passes instead of one prompt

A single "watch this and tell me if it is safe" call is a demo, not a system. It
gives you prose you cannot audit, no independent corroboration, and a decision you
cannot unit-test. Splitting reasoning (Pegasus) from targeted detection (Marengo
search) gives clickable timestamped evidence per policy and lets corroboration
raise or lower confidence explicitly.

## Policy taxonomy

Policies live in `config/policies.yaml`, mapped to the GARM Brand Safety Floor and
Suitability Framework. Five categories ship by default: hate/harassment,
drugs/illegal, profanity, unsafe product usage, and medical/cosmetic claims, plus
a campaign relevance gate. Each policy declares its GARM floor flag, suitability
tier, block and review severity thresholds, and the Marengo search probes used to
gather evidence. New advertiser or tolerance: edit YAML, not code.

Note: GARM the organisation was disbanded by the WFA in August 2024, but its
framework remains the de facto industry standard embedded in IAS, DoubleVerify and
Oracle verification. Greenlight adopts the framework, not the defunct body.

## Decision logic (config-driven)

Severity scale: none < low < medium < high. Per policy, `block_at` and `review_at`
set the thresholds. Overall: BLOCK outranks REVIEW outranks APPROVE.

1. Off-brief (low relevance and model agrees) -> BLOCK, not eligible to run.
2. GARM floor category, corroborated, at or above block severity -> BLOCK.
3. Any policy at or above its `block_at` -> BLOCK.
4. Any policy at or above its `review_at` -> REVIEW.
5. Otherwise -> APPROVE.

Confidence and human-in-the-loop: two-source agreement is high confidence, a
single source is medium. Any automated APPROVE or BLOCK below the configured
minimum confidence is downgraded to REVIEW so a human looks at it. A corroborated
GARM-floor block is the only call allowed to auto-block at the floor.

## Run it

Runs in mock mode out of the box using fixtures. No API key needed, so it is safe
to run live.

```bash
pip install -r requirements.txt
python -m demo.run_demo --html       # prints decisions, writes demo/report.html
python tests/test_decision.py        # decision-engine unit tests
```

Against the live API:

```bash
cp .env.example .env                 # set TL_API_KEY
# then point the runner at real video paths and a real index
```

## What is real and what is mocked

The TwelveLabs integration in `src/client.py` is written against the documented
v1.3 REST endpoints (`/tasks`, `/analyze`, `/search`) with the correct request and
response shapes. Every network call has a fixture-backed mock counterpart so the
pipeline runs in CI and in a demo without a key, upload latency or quota spend. In
a real deployment the fixtures become recorded-response contract tests. The four
demo scenarios in `fixtures/` are crafted to exercise every decision path.

## Scaling notes (for the architecture discussion)

- Indexing is async. Submit to `/tasks`, resume on the `index.task.ready` webhook
  (HMAC-signed), do not block a worker on long indexing jobs.
- Index once, query many. Embeddings are cached, so repeat policy probes are cheap.
  Reserve the generative Pegasus pass for creatives that pass the cheap relevance
  pre-filter.
- A queue plus a bounded worker pool (concurrent-task limits: 25 on the Developer
  plan, custom on Enterprise) handles batch pre-publish review.
- REVIEW-tier and low-confidence items route to human moderators by design.

## Repo layout

```
config/      policies.yaml (GARM-mapped taxonomy), campaign_brief.yaml
src/         client, relevance, analyze, search, decision, pipeline, schemas
fixtures/    analyze/ and search/ recorded responses for four scenarios
demo/        run_demo.py (CLI), report.py (HTML evidence report)
tests/       decision-engine unit tests
```

## Honest limitations

- Pegasus can hallucinate. That is exactly why the decision is deterministic and
  REVIEW routes to humans.
- Indexing adds latency on long videos; the pipeline is built async for this.
- Relevance score normalisation uses an empirical ceiling that should be
  calibrated per index from a labelled set, not guessed.
- The cosmetic-versus-drug claim line (FDA) is nuanced; a real deployment should
  involve counsel for the claims taxonomy.
- API surface moves fast. Re-verify model names and endpoints against live docs
  before relying on them.
```
