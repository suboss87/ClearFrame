<h1 align="center">ClearFrame</h1>

<p align="center"><strong>Brand-safe clearance for creator video ads.</strong></p>

<p align="center">
  Creators increasingly submit their own videos as the ad creative itself. Before one of those
  videos runs as a paid ad, ClearFrame checks it: is it on-brief, is it compliant, and can every
  call be explained to the advertiser with a timestamp. For every creative it returns an
  <strong>APPROVE&nbsp;/&nbsp;REVIEW&nbsp;/&nbsp;BLOCK</strong> decision, an auto-generated description, and
  <strong>timestamped evidence</strong> for every reason behind the call.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-34d399.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/React-18-22d3ee?logo=react&logoColor=black" alt="React 18" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Video%20AI-TwelveLabs-7c3aed" alt="TwelveLabs" />
</p>

<p align="center"><img src="docs/screenshot.png" alt="ClearFrame reviewer console" width="100%" /></p>

> **The model perceives. The engine decides.**
> TwelveLabs Pegasus reads a video across visuals, speech, and on-screen text in one pass. A
> separate, **deterministic** policy engine turns that perception into the verdict. In an ads
> system a wrong auto-block on a large advertiser is a revenue and trust incident, not just a bug,
> so the call that matters is never left to a language model alone.

---

## Who this is for and what it solves

The Ads Compliance team at a social platform has to clear every creator video before it can run as
a paid ad, at scale, with an explanation they can defend to the advertiser. ClearFrame is that
clearance gate. It is built for the reviewer working the queue, not as a model demo: every verdict
comes with a plain-English reason and a clickable timestamp, and every campaign carries its own
policy configuration, so the same engine can run a strict pharmaceutical-adjacent campaign and a
relaxed lifestyle campaign without a code change.

## Highlights

- **Three-pane reviewer console.** Searchable, foldered queue, evidence timeline, and decision panel, all on one screen.
- **Real video understanding.** TwelveLabs Pegasus reads visuals, speech, and on-screen text in a single pass and returns a description, an on-brief judgement with a stated reason, and structured policy findings with timestamps.
- **Deterministic verdicts.** A config-driven policy engine (no LLM makes the final call) that is auditable, tunable, and consistent across runs.
- **Timestamped evidence.** Every flagged moment is a clip you click and the player jumps straight to it, then pauses at the end of the flagged window instead of playing on.
- **Per-campaign governance.** A master prompt, policy toggles, profanity tolerance, and a relevance threshold are set once per campaign and injected into every review run against it.
- **Chat with the video.** Ask anything about a creative. Known questions (why this verdict, is it on-brief) answer instantly from the already-computed decision; open-ended questions fall through to a live TwelveLabs call that reads the actual video.
- **Live progress, correctly attributed.** A creative processing for a campaign renders inside that campaign's own folder, not a disconnected global list, and a failed run shows the real error instead of vanishing.
- **Human in the loop.** The system auto-decides by default; a human can override any verdict with a comment, and the override can itself be undone, both actions logged to an append-only audit trail.
- **Runs with zero setup.** Mock mode uses recorded fixtures, so the whole app works before you add a key.

## Quickstart

```bash
make install          # backend (pip) + frontend (npm) deps
make seed             # reset to one demo campaign with four sample creatives
make api              # FastAPI backend on http://localhost:8000
make web              # Vite frontend on http://localhost:5000 (auto-increments if that port is busy)
```

Open the frontend. It detects the backend and runs **live**. Everything works in **mock mode** out
of the box, no key, no quota. To run on real videos:

1. Open **Settings** (bottom-left), paste your **TwelveLabs API key**, save. It is validated
   against TwelveLabs, then **encrypted at rest** server-side; the browser only ever sees a masked
   preview.
2. Create a **campaign**: set its brief, master prompt, policy toggles, profanity tolerance, and a
   linked upload bucket.
3. Upload a video, or drop one in the linked bucket. A background sync picks up bucket uploads
   automatically within 30 seconds.
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

1. **Pre-check.** A deterministic gate on the file itself: format, size, duration, and a
   content-hash dedup, scoped per campaign so the same creative can legitimately run through two
   campaigns with different policy configurations. Nothing here spends a TwelveLabs call.
2. **Perception.** One Pegasus call reads the whole clip and returns a 2 to 5 sentence description,
   an on-brief judgement with a one-sentence rationale, a 0 to 1 relevance score against the
   campaign brief, and a findings list, each with a category, a severity, and the precise second
   the violation is seen or heard.
3. **Decision engine.** Plain, deterministic Python. Each finding's severity is compared against
   that campaign's `block_at` / `review_at` thresholds; the off-brief gate contributes its own
   BLOCK if relevance is below threshold and the model judged it off-brief; the overall verdict is
   the most severe contribution. A low-confidence automated call is downgraded to REVIEW instead
   of being acted on.

Nothing in step 3 calls a model. It is why an offline eval harness can validate the engine
deterministically (see below), and why changing a threshold is a config edit you can test, not a
prompt you have to hope holds.

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

The data and storage layers are **config-swappable**: set `DATABASE_URL` for Supabase Postgres, or
`SUPABASE_*` to store videos in Supabase Storage. No code changes; see [Configuration](#configuration).

Marengo 3.0 remains co-resident at indexing and is available for reviewer-driven exploratory
search, but it does not sit in the automated decision path. Its `/search` endpoint stopped
returning a numeric score in this API version, so relevance and evidence both come from the
single Pegasus pass described above. That is a real API change discovered mid-build, and adapting
to it cleanly, with tests and the eval harness still green, is part of the engineering story here,
not something to gloss over.

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
Suitability Framework: hate/harassment, drugs/illegal, profanity, unsafe product usage, and
medical/cosmetic claims, plus a campaign relevance gate. Adding a category or changing a tolerance
is a **config edit, not a code change**, and each campaign can set its own thresholds, its own
profanity tolerance, and its own master prompt on top of this shared taxonomy.

## Testing and evaluation

```bash
make test     # decision-engine unit tests (5/5)
make eval     # score the engine against the labeled set: precision/recall + confusion matrix
make demo     # run the pipeline over the four samples in mock mode, write an HTML report
```

`make eval` runs a labeled set of 16 compliance scenarios through the real decision engine and
reports a verdict confusion matrix, per-policy precision/recall, and the cost-weighted errors that
actually matter: *false blocks* (hurt the advertiser) and *missed flags* (hurt brand safety).
Current result: **16/16, 100% verdict accuracy, 0 false blocks, 0 missed flags**
([full report](backend/eval/REPORT.md), [how it works](backend/eval/README.md)). The set
deliberately probes the subtle rules, so relaxing any threshold trips a failure with a non-zero
exit code; it doubles as a regression gate, and runs on every push and pull request (see
[CI](#continuous-integration) below). It measures the deterministic engine, holding model
perception fixed; perception accuracy is a separate layer that needs labeled real videos.

## Continuous integration

Every push and pull request runs `make test` and `make eval` in GitHub Actions
([workflow](.github/workflows/ci.yml)). A policy change that breaks a labeled case fails the build
before it reaches a live advertiser, the same regression-gate story the eval harness tells, made
real rather than asserted.

## Deployment

Local development uses SQLite and local disk by default. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for two ready paths to a real deployment: a quick path
(Vercel for the frontend, Render for the backend) and a cloud production path (AWS App Runner, S3,
CloudFront), including the one architectural change that matters when scaling past a single
backend instance.

## Status

What runs today: the full pipeline, a live FastAPI API (campaigns, bucket sync, progress, chat,
decisions), an encrypted key store, a Supabase-ready data and storage layer, a human override and
audit trail, and the reviewer UI, end to end, mock or live. What a deployed multi-tenant product
still needs: managed hosting, auth and per-advertiser tenancy, a real queue in place of the
in-process background sync, and monitoring. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the
scaling path and [`docs/Clearframe_Design_Doc.pdf`](docs/Clearframe_Design_Doc.pdf) for the full
design and scale story.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: open an issue, branch, keep changes small and
tested, and run `make test` before a PR.

## License

[MIT](LICENSE)
