<h1 align="center">ClearFrame</h1>

<p align="center"><strong>Brand-safe clearance for creator video ads — a verdict you can audit.</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-34d399.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/React-18-22d3ee?logo=react&logoColor=black" alt="React 18" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Video%20AI-TwelveLabs-7c3aed" alt="TwelveLabs" />
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#how-a-decision-is-made">How it works</a> ·
  <a href="#why-you-can-trust-the-verdict">Why you can trust it</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#testing-and-evaluation">Evaluation</a> ·
  <a href="#deployment">Deployment</a>
</p>

<p align="center"><img width="1462" height="649" alt="ClearFrame high-level architecture: creator upload through pre-check, TwelveLabs perception, the decision engine, and reviewer override" src="https://github.com/user-attachments/assets/96c0577f-7884-4499-915a-726ec5e97259" /></p>

> **The model perceives. The engine decides.**
> TwelveLabs reads what happens across visuals, speech, and on-screen text. A separate,
> **deterministic** policy engine turns that into an **APPROVE / REVIEW / BLOCK** verdict — because in
> an ads system, a wrong auto-block on a large advertiser is a revenue and trust incident, not just a bug.

---

## The problem

A social platform's ad revenue depends on creator videos running as paid ads. Before one runs, an
Ads Compliance team has to clear it: is it safe, is it actually about the product, and can they
defend the call to the advertiser if they block it. Doing that by hand does not scale past a
handful of submissions a day, and getting it wrong is expensive either way — block a clean video and
the advertiser loses reach; approve a bad one and the platform's brand safety is on the line.

## The insight

The obvious move is to ask a video-understanding model for the verdict directly. That does not hold
up in an ads system: a single wrong auto-block on a large advertiser is a revenue and trust incident,
and a model's judgment cannot be unit-tested, versioned, or explained the way a policy needs to be.
So ClearFrame splits the problem in two:

- **TwelveLabs perceives.** It reads visuals, speech, and on-screen text, and returns a description,
  an on-brief judgment, a relevance score, and policy findings with exact timestamps.
- **A deterministic engine decides.** Plain Python compares those findings against a campaign's
  thresholds and returns APPROVE, REVIEW, or BLOCK. **No language model ever makes the final call.**

That single split is what makes every verdict auditable, tunable per advertiser, and reproducible.

## What it does

For every creative: a verdict with a plain-English reason, a clickable timestamp for every flagged
moment, and a human who can always override with a comment. Each campaign carries its own brief,
policy thresholds, and profanity tolerance, so the same engine runs a strict pharma-adjacent brand
and a relaxed lifestyle brand without a code change. Because the decision engine is plain Python —
not a prompt — a labeled evaluation set can prove it stays correct as policies change. And the whole
thing runs with **zero setup**: mock mode uses recorded fixtures, so it works before you add an API key.

<p align="center"><img width="1918" height="988" alt="ClearFrame reviewer console showing a BLOCK verdict with relevance score, flagged policies, and timestamped evidence" src="https://github.com/user-attachments/assets/0cd8d5a6-3d80-4d80-9e20-23674ce83baf" /></p>

<p align="center"><em>The reviewer console: verdict, relevance, flagged policies, and a clickable timestamp for every reason.</em></p>

## Quickstart

Runs end to end in **mock mode** with no key and no quota — every command below works on a fresh clone.

```bash
make install          # backend (pip) + frontend (npm) deps
make seed             # reset to one demo campaign with four sample creatives
make api              # FastAPI backend on http://localhost:8000
make web              # Vite frontend on http://localhost:5000 (auto-increments if the port is busy)
```

Open the frontend — it detects the backend and runs live. You should land on a seeded campaign with
four creatives already scored: a clean APPROVE, a REVIEW, and a BLOCK you can click into to see the
timestamped evidence.

<details>
<summary><strong>Run it on real videos (add a TwelveLabs key)</strong></summary>

<br />

1. Open **Settings**, paste your **TwelveLabs API key**, and save. It is validated against TwelveLabs,
   then **encrypted at rest** server-side — the browser only ever sees a masked preview.
2. Create a **campaign**: brief, master prompt, policy toggles, profanity tolerance, and (optionally)
   a linked upload bucket.
3. **Upload** a video, or drop one in the linked bucket — background sync picks up bucket uploads
   within ~30 seconds.
4. Watch the live stages, then the verdict, evidence timeline, and chat.

> No backend running? The frontend falls back to a self-contained demo so it always renders.

</details>

## How a decision is made

```
 ┌───────────┐   ┌────────────────────────────┐   ┌────────────────┐
 │ Pre-check │ → │ TwelveLabs (Pegasus)       │ → │ Decision engine│
 │ (format,  │   │ description, relevance,    │   │ (deterministic)│
 │  dedup)   │   │ on-brief, findings + times │   │                │
 └───────────┘   └────────────────────────────┘   └────────────────┘
```

1. **Pre-check.** Format, size, duration, and per-campaign content-hash dedup — all local and
   deterministic. Junk (empty files, screenshots renamed to `.mp4`, 90-minute exports, duplicates)
   is blocked here and **never spends a TwelveLabs call**.
2. **Perception.** One Pegasus pass returns a 2–5 sentence description, an on-brief judgment with a
   reason, a 0–1 relevance score, and per-finding category, severity, and exact timestamp.
3. **Decision engine.** Plain, deterministic Python. Each finding's severity is compared against that
   campaign's `block_at` / `review_at` thresholds; an off-brief creative below the relevance threshold
   contributes its own BLOCK; the overall verdict is the most severe contribution. Low-confidence
   auto-decisions downgrade to REVIEW so a human looks.

Because no model runs in step 3, the eval harness can validate the engine deterministically — a
threshold change is a config edit you can test, not a prompt you hope holds.

## Why you can trust the verdict

Trust is the whole point of an ads-compliance gate, so it is designed in, not asserted:

- **Deterministic by construction.** The verdict comes from explicit rules in
  [`decision.py`](backend/src/decision.py), driven by [`policies.yaml`](backend/config/policies.yaml).
  The same inputs always produce the same verdict.
- **Every verdict is explainable.** Each result carries plain-English `reasons` that trace to a
  specific rule and finding — "BLOCK: unsafe product usage at severity high [GARM floor]" — with a
  clickable timestamp, not a black-box score.
- **Fail-safe defaults.** A low-confidence automated APPROVE or BLOCK is downgraded to human REVIEW.
  The one deliberate exception is a corroborated GARM Brand Safety Floor block, which stays blocked.
- **Human-in-the-loop, on the record.** A reviewer can override any verdict; the override and comment
  are stored in an audit trail alongside the automated call.
- **Regression-gated.** A labeled evaluation set runs on every push and pull request (see
  [Evaluation](#testing-and-evaluation)). A policy change that breaks a case fails the build before
  it can reach a live advertiser.

## Architecture

| Layer | Tech | Role |
|---|---|---|
| **Frontend** | React 18 + Vite | Three-pane reviewer console; live or demo mode |
| **API** | FastAPI | Campaigns, uploads, bucket sync, live stage progress, chat, decisions |
| **Perception** | TwelveLabs v1.3 (Marengo 3.0 indexing, Pegasus 1.2 analysis) | Indexing, relevance, reasoning, evidence |
| **Decision** | Pure-Python rules engine | Deterministic APPROVE / REVIEW / BLOCK |
| **Data** | SQLite (default) or Supabase Postgres | Campaigns, reviews, audit trail, settings |
| **Storage** | Local disk (default) or Supabase Storage | Uploaded videos |
| **Secrets** | Fernet-encrypted | TwelveLabs key never leaves the server in plaintext |

Data and storage are **config-swappable**: set `DATABASE_URL` for Supabase Postgres, or `SUPABASE_*`
for Supabase Storage — no code change (see [Configuration](#configuration)).

> **A real API change, handled cleanly.** Marengo 3.0 still handles indexing and reviewer search, but
> sits outside the automated decision path: its `/search` endpoint stopped returning a numeric score
> in this API version, so relevance and evidence both come from the Pegasus pass. Found mid-build,
> adapted without changing the contract — tests and eval stayed green.

## Policy taxonomy

Policies live in [`backend/config/policies.yaml`](backend/config/policies.yaml), mapped to the GARM
Brand Safety Floor and Suitability Framework: hate/harassment, drugs/illegal, profanity, unsafe
product usage, medical/cosmetic claims — plus a relevance gate. Adding a category or changing a
tolerance is a **config edit, not a code change**; each campaign sets its own thresholds, tolerance,
and master prompt on top of this shared taxonomy.

## Testing and evaluation

```bash
make test     # decision-engine unit tests (5/5)
make eval     # score the engine against the labeled set: precision/recall + confusion matrix
make demo     # run the pipeline over the four samples in mock mode, write an HTML report
```

`make eval` runs the decision engine against a labeled set of compliance scenarios and reports a
confusion matrix, per-policy precision/recall, and the two errors that actually cost something —
*false blocks* (hurt the advertiser) and *missed flags* (hurt brand safety). It passes **16/16**
today ([full report](backend/eval/REPORT.md) · [how it works](backend/eval/README.md)).

This is a **correctness gate on the deterministic engine**: given a set of model perceptions, the
rules produce the intended verdict every time — reproducible, auditable, regression-gated. The set is
deliberately small and hand-authored, meant to grow as real cases turn up, not a claim of finished
coverage. It does **not** measure whether the model correctly *sees* a violation in a real video —
perception accuracy is a separate, harder problem that needs labeled real footage.

## Continuous integration

Every push and pull request runs `make test` and `make eval` in GitHub Actions
([workflow](.github/workflows/ci.yml)). The eval doubles as a regression gate — a policy change that
breaks a labeled case fails the build.

## Deployment

Local development uses SQLite and local disk by default. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for two paths — quick (Vercel for the frontend, Render for
the backend) and cloud (AWS App Runner, S3, CloudFront) — including the one change that matters when
scaling past a single backend instance.

## Status

**Runs today:** the full pipeline, a live FastAPI API, an encrypted key store, a Supabase-ready data
and storage layer, human override with an audit trail, and the reviewer UI — mock or live.

**Still needed for a deployed multi-tenant product:** managed hosting, auth and per-advertiser
tenancy, a real queue in place of the in-process sync, and monitoring. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) and
[`docs/Clearframe_Design_Doc.pdf`](docs/Clearframe_Design_Doc.pdf) for the full story.

<details>
<summary><strong>Project structure</strong></summary>

<br />

```
clearframe/
├── backend/
│   ├── api.py                 # FastAPI app: campaigns, uploads, bucket sync, progress, chat, decisions, settings
│   ├── seed_demo.py           # `make seed`, one demo campaign with four samples
│   ├── src/
│   │   ├── client.py          # TwelveLabs v1.3 REST client (+ fixture-backed mock)
│   │   ├── pipeline.py        # orchestrates pre-check, Pegasus analysis, decision, streams progress
│   │   ├── decision.py        # the deterministic policy engine (the heart of the system)
│   │   ├── analyze.py         # builds the Pegasus prompt, parses the structured response
│   │   ├── precheck.py        # format / size / duration / dedup gate, before any model spend
│   │   ├── bucket_sync.py     # per-campaign background sync from a Supabase Storage bucket
│   │   ├── schemas.py         # pydantic contracts for every stage's output
│   │   ├── db.py              # SQLite / Supabase Postgres data layer
│   │   ├── keystore.py        # Fernet-encrypted API key storage
│   │   ├── indexes.py         # TwelveLabs index lifecycle
│   │   └── storage.py         # Supabase Storage upload, download, and signed URLs
│   ├── config/                # GARM-mapped policy taxonomy (policies.yaml)
│   ├── fixtures/              # recorded TwelveLabs responses for the demo scenarios
│   ├── eval/                  # labeled evaluation set + the harness that scores the engine against it
│   └── tests/                 # decision-engine unit tests
├── frontend/
│   └── src/ClearframeApp.jsx  # the three-pane reviewer console, single file by design
└── docs/                      # architecture diagrams, design doc, screenshots, deployment guide
```

</details>

<details>
<summary><strong>Configuration</strong></summary>

<br />

Copy `backend/.env.example` to `backend/.env`. All values are optional; unset means mock or local.

| Variable | Purpose |
|---|---|
| `TL_API_KEY` | TwelveLabs key (or set it in the UI under Settings, stored encrypted) |
| `DATABASE_URL` | Postgres / Supabase connection string. Unset means local SQLite |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET` | Store uploaded videos in Supabase Storage. Unset means local disk |

Check what is active any time: `curl localhost:8000/api/health` returns `{ mock, db, storage }`.

</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: open an issue, branch, keep changes small and
tested, and run `make test` before a PR.

## License

[MIT](LICENSE)
