<h1 align="center">ClearFrame</h1>

<p align="center"><strong>Brand-safe clearance for creator video ads.</strong></p>

<p align="center">
  Creators now submit their own videos as the ad creative itself. ClearFrame checks each one before
  it runs: on-brief, compliant, every call explainable with a timestamp. It returns
  <strong>APPROVE&nbsp;/&nbsp;REVIEW&nbsp;/&nbsp;BLOCK</strong>, an auto-generated description, and
  <strong>timestamped evidence</strong> for every reason.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-34d399.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/React-18-22d3ee?logo=react&logoColor=black" alt="React 18" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Video%20AI-TwelveLabs-7c3aed" alt="TwelveLabs" />
</p>

<p align="center"><img width="1462" height="649" alt="ClearFrame HLD" src="https://github.com/user-attachments/assets/96c0577f-7884-4499-915a-726ec5e97259" /></p>

<p align="center"><img width="1918" height="988" alt="Screenshot 2026-07-01 at 18 53 07" src="https://github.com/user-attachments/assets/0cd8d5a6-3d80-4d80-9e20-23674ce83baf" /></p>


> **The model perceives. The engine decides.**
> TwelveLabs Pegasus reads a video (visuals, speech, on-screen text) in one pass. A separate,
> **deterministic** policy engine turns that into the verdict. A wrong auto-block on a large
> advertiser is a revenue and trust incident, so the call itself never rests on a language model
> alone.

---

## Who this is for and what it solves

An Ads Compliance team must clear every creator video before it runs as a paid ad, at scale, with a
reason they can defend to the advertiser. ClearFrame is that clearance gate, built for the reviewer,
not a model demo. Every verdict carries a plain-English reason and a clickable timestamp. Every
campaign carries its own policy configuration: one engine runs a strict pharma-adjacent campaign and
a relaxed lifestyle campaign, no code change.

## Highlights

- **Three-pane reviewer console.** Queue, evidence timeline, decision panel, one screen.
- **Real video understanding.** One Pegasus pass returns a description, an on-brief judgment with a
  reason, and structured findings with timestamps.
- **Deterministic verdicts.** Config-driven policy engine, no LLM makes the final call, auditable
  and consistent.
- **Timestamped evidence.** Click a flagged moment, the player jumps there and pauses at the end.
- **Per-campaign governance.** Master prompt, policy toggles, profanity tolerance, and relevance
  threshold, set once per campaign.
- **Chat with the video.** Known questions answer instantly from the computed decision; anything
  else triggers a live TwelveLabs call.
- **Live progress, correctly attributed.** A creative renders inside its own campaign folder;
  failures show the real error.
- **Human in the loop.** Auto-decides by default; a human can override with a comment, the override
  can itself be undone, both logged to an audit trail.
- **Zero setup.** Mock mode uses recorded fixtures, so the app works before you add a key.

## Quickstart

```bash
make install          # backend (pip) + frontend (npm) deps
make seed             # reset to one demo campaign with four sample creatives
make api              # FastAPI backend on http://localhost:8000
make web              # Vite frontend on http://localhost:5000 (auto-increments if that port is busy)
```

Open the frontend. It detects the backend and runs **live**. Everything works in **mock mode** out
of the box, no key, no quota. To run on real videos:

1. Open **Settings**, paste your **TwelveLabs API key**, save. It validates against TwelveLabs,
   then is **encrypted at rest** server-side; the browser only ever sees a masked preview.
2. Create a **campaign**: brief, master prompt, policy toggles, profanity tolerance, linked upload
   bucket.
3. Upload a video, or drop one in the linked bucket. Background sync picks up bucket uploads within
   30 seconds.
4. Watch the live stages, then the verdict, evidence timeline, and chat.

> No backend running? The frontend falls back to a self-contained demo so it always renders.

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

## Project structure

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

`make eval` scores 16 labeled compliance scenarios through the real decision engine: a confusion
matrix, per-policy precision/recall, and the errors that matter most, *false blocks* (hurt the
advertiser) and *missed flags* (hurt brand safety). Current result: **16/16, 100% verdict accuracy,
0 false blocks, 0 missed flags** ([full report](backend/eval/REPORT.md),
[how it works](backend/eval/README.md)). Runs on every push and pull request as a regression gate
(see [CI](#continuous-integration)) and measures the deterministic engine only; perception accuracy
is a separate layer that needs labeled real videos.

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
