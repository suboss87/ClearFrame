<h1 align="center">ClearFrame</h1>

<p align="center"><strong>Brand-safe clearance for creator video ads.</strong></p>

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
  <a href="#architecture">Architecture</a> ·
  <a href="#testing-and-evaluation">Evaluation</a> ·
  <a href="#deployment">Deployment</a>
</p>

<p align="center"><img width="1462" height="649" alt="ClearFrame high-level architecture: creator upload through pre-check, TwelveLabs perception, the decision engine, and reviewer override" src="https://github.com/user-attachments/assets/96c0577f-7884-4499-915a-726ec5e97259" /></p>

## The problem

A social platform's ad revenue depends on creator videos running as paid ads. Before one runs, an
Ads Compliance team has to clear it: is it safe, is it actually about the product, and can they
defend the call to the advertiser if they block it. Doing that by hand does not scale past a
handful of submissions a day, and getting it wrong is expensive either way: block a clean video and
the advertiser loses reach, approve a bad one and the platform's brand safety is on the line.

## The insight

The obvious move is to ask a video-understanding model for a verdict directly. That does not hold
up in an ads system: a single wrong auto-block on a large advertiser is a revenue and trust
incident, and a model's judgment cannot be unit-tested, versioned, or explained the way a policy
needs to be. So ClearFrame splits the problem in two. TwelveLabs **perceives** the video: it reads
visuals, speech, and on-screen text, and returns a description, an on-brief judgment, and findings
with timestamps. A separate, **deterministic** policy engine **decides**: it compares those findings
against a campaign's thresholds and returns APPROVE, REVIEW, or BLOCK. No language model ever makes
the final call.

## What it does

For every creative: a verdict with a plain-English reason, a clickable timestamp for every flagged
moment, and a human who can always override with a comment. Each campaign carries its own brief,
policy thresholds, and profanity tolerance, so the same engine runs a strict pharma-adjacent brand
and a relaxed lifestyle brand without a code change. Because the decision engine is plain Python,
not a prompt, a labeled evaluation set can check it stays correct as policies change, a small,
growing set today, not a claim of finished coverage. The whole thing runs with zero setup: mock
mode uses recorded fixtures, so it works before you add an API key.

<p align="center"><img width="1918" height="988" alt="ClearFrame reviewer console showing a BLOCK verdict with relevance score, flagged policies, and timestamped evidence" src="https://github.com/user-attachments/assets/0cd8d5a6-3d80-4d80-9e20-23674ce83baf" /></p>

---

## Quickstart

```bash
make install          # backend (pip) + frontend (npm) deps
make seed             # reset to one demo campaign with four sample creatives
make api              # FastAPI backend on http://localhost:8000
make web              # Vite frontend on http://localhost:5000 (auto-increments if that port is busy)
```

Open the frontend. It detects the backend and runs **live**. Everything above works in **mock
mode**, no key, no quota.

> No backend running? The frontend falls back to a self-contained demo so it always renders.

<details>
<summary><strong>Run it on real videos (add a TwelveLabs key)</strong></summary>

1. Open **Settings**, paste your **TwelveLabs API key**, save. It validates against TwelveLabs,
   then is **encrypted at rest** server-side; the browser only ever sees a masked preview.
2. Create a **campaign**: brief, master prompt, policy toggles, profanity tolerance, linked upload
   bucket.
3. Upload a video, or drop one in the linked bucket. Background sync picks up bucket uploads within
   30 seconds.
4. Watch the live stages, then the verdict, evidence timeline, and chat.

</details>

## How a decision is made

```
 ┌──────────┐   ┌────────────────────────────┐   ┌────────────────┐
 │ Pre-check│ → │ TwelveLabs (Pegasus)       │ → │ Decision engine│
 │(format,  │   │ description, relevance,    │   │ (deterministic)│
 │ dedup)   │   │ on-brief, findings + times │   │                │
 └──────────┘   └────────────────────────────┘   └────────────────┘
```

1. **Pre-check.** Format, size, duration, per-campaign content-hash dedup. No TwelveLabs call spent
   here.
2. **Perception.** One Pegasus call returns a 2 to 5 sentence description, an on-brief judgment with
   a reason, a 0 to 1 relevance score, and per-finding category, severity, and exact timestamp.
3. **Decision engine.** Plain, deterministic Python. Each finding's severity is compared against
   that campaign's `block_at` / `review_at` thresholds; off-brief below threshold contributes its
   own BLOCK; the overall verdict is the most severe contribution. Low-confidence calls downgrade
   to REVIEW.

No model runs in step 3, so the eval harness can validate the engine deterministically, and a
threshold change is a config edit you can test, not a prompt you hope holds.

## Architecture

| Layer | Tech | Role |
|---|---|---|
| **Frontend** | React 18 + Vite | Three-pane reviewer console; live or demo mode |
| **API** | FastAPI | Campaigns, uploads, bucket sync, live stage progress, chat, decisions |
| **Perception** | TwelveLabs v1.3 (Marengo 3.0 for indexing, Pegasus 1.2 for analysis) | Indexing, relevance, reasoning, evidence |
| **Decision** | Pure-Python rules engine | Deterministic APPROVE / REVIEW / BLOCK |
| **Data** | SQLite (default) or Supabase Postgres | Campaigns, reviews, audit trail, settings |
| **Storage** | Local disk (default) or Supabase Storage | Uploaded videos |
| **Secrets** | Fernet-encrypted | TwelveLabs key never leaves the server in plaintext |

Data and storage are **config-swappable**: set `DATABASE_URL` for Supabase Postgres, or
`SUPABASE_*` for Supabase Storage. No code change, see [Configuration](#configuration).

Marengo 3.0 still handles indexing and reviewer search, but sits outside the automated decision
path: its `/search` endpoint stopped returning a numeric score in this API version, so relevance
and evidence both come from the Pegasus pass above. A real API change found mid-build, adapted
cleanly, tests and eval still green.

<details>
<summary><strong>Project structure</strong></summary>

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
│   ├── fixtures/               # recorded TwelveLabs responses for the demo scenarios
│   ├── eval/                   # labeled evaluation set + the harness that scores the engine against it
│   └── tests/                 # decision-engine unit tests
├── frontend/
│   └── src/ClearframeApp.jsx  # the three-pane reviewer console, single file by design
└── docs/                      # architecture diagrams, design doc, screenshots, deployment guide
```

</details>

## Configuration

Copy `backend/.env.example` to `backend/.env`. All values are optional; unset means mock or local.

| Variable | Purpose |
|---|---|
| `TL_API_KEY` | TwelveLabs key (or set it in the UI under Settings, stored encrypted) |
| `DATABASE_URL` | Postgres / Supabase connection string. Unset means local SQLite |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET` | Store uploaded videos in Supabase Storage. Unset means local disk |

Check what is active any time: `curl localhost:8000/api/health` returns `{ mock, db, storage }`.

## Policy taxonomy

Policies live in `backend/config/policies.yaml`, mapped to the GARM Brand Safety Floor and
Suitability Framework: hate/harassment, drugs/illegal, profanity, unsafe product usage,
medical/cosmetic claims, plus a relevance gate. Adding a category or changing a tolerance is a
**config edit, not a code change**; each campaign sets its own thresholds, tolerance, and master
prompt on top of this shared taxonomy.

## Testing and evaluation

```bash
make test     # decision-engine unit tests (5/5)
make eval     # score the engine against the labeled set: precision/recall + confusion matrix
make demo     # run the pipeline over the four samples in mock mode, write an HTML report
```

`make eval` runs the decision engine against a labeled set of compliance scenarios and reports a
confusion matrix, per-policy precision/recall, and the two errors that actually cost something,
*false blocks* (hurt the advertiser) and *missed flags* (hurt brand safety). It passes 16/16 today
([full report](backend/eval/REPORT.md), [how it works](backend/eval/README.md)), but the set is
small and hand-authored, a work in progress meant to grow as more real cases turn up, not a claim
of finished coverage. It measures the deterministic engine only; perception accuracy needs labeled
real videos, a separate and harder problem. It still runs on every push and pull request as a
regression gate (see [CI](#continuous-integration)).

## Continuous integration

Every push and pull request runs `make test` and `make eval` in GitHub Actions
([workflow](.github/workflows/ci.yml)). A policy change that breaks a labeled case fails the build
before it reaches a live advertiser.

## Deployment

Local development uses SQLite and local disk by default. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for two paths: quick (Vercel for the frontend, Render
for the backend) and cloud (AWS App Runner, S3, CloudFront), including the one change that matters
when scaling past a single backend instance.

## Status

Runs today: the full pipeline, a live FastAPI API, an encrypted key store, a Supabase-ready data
and storage layer, human override with an audit trail, and the reviewer UI, mock or live. Still
needed for a deployed multi-tenant product: managed hosting, auth and per-advertiser tenancy, a
real queue in place of the in-process sync, and monitoring. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) and
[`docs/Clearframe_Design_Doc.pdf`](docs/Clearframe_Design_Doc.pdf) for the full story.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: open an issue, branch, keep changes small and
tested, and run `make test` before a PR.

## License

[MIT](LICENSE)
