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
  <a href="#why-i-built-this">Why</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#try-it">Try it</a> ·
  <a href="#using-it-for-your-own-policies">Adopting it</a> ·
  <a href="#whats-done-whats-not">Status</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#deployment">Deployment</a>
</p>

<p align="center"><em>A brand pays the platform; the platform's compliance team uses ClearFrame to<br/>clear creator videos before they run as ads.</em></p>

**At a glance**
- **What it is:** an AI compliance gate for creator ads, brand-safety and campaign-fit checked before a video runs.
- **Why the model doesn't decide:** TwelveLabs perceives the video, a deterministic rule engine (plain Python code) compares it to your thresholds and calls the verdict.
- **What proves it works:** a labeled eval set and unit tests, both automated (see [Testing and evaluation](#testing-and-evaluation)).

**Key concepts, quick read**
- **Relevance score (0 to 1):** Pegasus's own estimate of brief-fit, not something this code computes. It only blocks combined with an off-brief judgment: score below 0.55 and Pegasus itself calling the video off-brief. A low score alone never blocks a video Pegasus still calls on-brief.
- **Perceive vs decide:** TwelveLabs writes the report, description, findings, timestamps. `decision.py` reads that report against `policies.yaml` and returns APPROVE, REVIEW, or BLOCK. The model never makes that last call.
- **Two evals, both offline:** `make eval` checks the rulebook, 16 hand-written cases, holding perception fixed; runs in CI on every push and PR. `perception_eval.py` checks whether the pipeline actually catches known violations in real videos, a manual smoke test on 4 clips, not wired into CI.

## Why I built this

**The problem:** social media platforms run creators' videos as paid ads. Before one goes live, the
compliance team has to be sure it's safe and on-brief, and be able to say why if they block it. By
hand that doesn't scale, and every wrong call costs money: block a good video and the advertiser
loses reach; approve a bad one and it's a brand-safety mess.

**Why the obvious fix falls short:** asking an AI "should this run?" and taking its word for it
can't be explained or tested, and a wrong auto-block on a big advertiser is a trust and revenue
hit, not just a bug.

**What ClearFrame does:** a compliance gate that uses [TwelveLabs](https://www.twelvelabs.io/) to index
and watch the video, then a deterministic engine makes the final call.

## How it works

<p align="center"><img width="1444" height="662" alt="ClearFrame pipeline: pre-check, perception, decision, human oversight" src="https://github.com/user-attachments/assets/da6c411d-a584-424b-a4f9-403ccfc90338" /></p>

A creator drops a video into a campaign's linked bucket, and it flows through four steps:

1. **Pre-check**, rule-based with ffprobe: format, size, duration, duplicates. Junk never spends a
   TwelveLabs call.
2. **Perception**: [Marengo](https://docs.twelvelabs.io/docs/concepts/models) indexes the video,
   then [Pegasus](https://docs.twelvelabs.io/docs/concepts/models) reads it once across visuals,
   speech, and on-screen text, returning a 2 to 5 sentence description, an on-brief judgment, a
   relevance score, and per-policy findings with timestamps.
3. **Decision**: the engine, plain Python, no model, compares those findings to the campaign's
   thresholds and returns APPROVE, REVIEW, or BLOCK.
4. **Human oversight**: a reviewer on the compliance team can override any verdict in the console;
   every outcome, automated or human, lands in an audit trail, and the creator is notified on a
   block.

A real trace, from a live run, not a fixture (full record in
[`docs/real_run_example.json`](docs/real_run_example.json)): Pegasus found an on-screen claim,
`"Clinically proven to clear acne"`, at `medical_claims` severity `high`. `policies.yaml` sets
`medical_claims: block_at: medium`. `high` meets `medium`, so the engine returned `BLOCK`,
timestamped to the second the text appears. Nothing here is a model's opinion, it's one finding
compared to one number in a YAML file.

<p align="center"><img width="1917" height="990" alt="Reviewer console showing a BLOCK verdict with timestamped evidence" src="https://github.com/user-attachments/assets/9953466d-1e77-4e08-a2b6-8bcfcacc1631" /></p>

**Why trust the output:**
- **Deterministic:** `decision.py`, the plain Python, makes the call, not the model, so the same findings always produce the same verdict.
- **Explainable:** every verdict traces to one finding and one threshold in `policies.yaml`, open and readable.
- **Regression-gated:** a labeled eval set runs in CI on every push; a threshold change that breaks a case fails the build.
- **Honest about the gap:** perception itself, whether Pegasus actually sees the violation, is smoke-tested on real videos, not yet benchmarked, see [What's done, what's not](#whats-done-whats-not).

**How this scales:** each video already processes independently, so more throughput means more
workers, not a redesign. Today it's one instance, one video at a time, roughly 30 to 90 seconds
each, measured on real runs. The fix, not yet built: a queue (SQS on the AWS path in
[`deployment/CLOUD_DEPLOY.md`](deployment/CLOUD_DEPLOY.md)) instead of a background thread, N
workers pulling from it. Throughput scales close to linearly, since videos share nothing but the
database and TwelveLabs, and both already handle concurrent access fine. (Everything else still
missing, auth, tenancy, and more, is in [What's done, what's not](#whats-done-whats-not).)

For the full treatment of both, [`docs/design_doc.html`](docs/design_doc.html) has dedicated
sections: "Why the outputs are trustworthy" and "Scaling in a real ads system."

---

## Try it

Two ways to run this: a quick mock demo with no setup, or the real pipeline against real videos.

### Quick demo, no API key

```
make install  →  make seed  →  make api  →  make web
```
(`api` and `web` are dev servers, run each in its own terminal.)

```bash
make install          # installs backend (pip) and frontend (npm) dependencies
make seed             # resets the database to one demo campaign with four scored creatives
make api              # starts the FastAPI backend on http://localhost:8000
make web              # starts the Vite frontend on http://localhost:5000
```

`make seed` leaves you with four creatives already run through the pipeline in mock mode: one
APPROVE, one REVIEW, and two BLOCKs, one for a policy violation, one for being off-brief. Open the
frontend and click into any of them to see the verdict and the timestamped evidence behind it.
Mock mode replays recorded fixtures, so this runs end to end with no TwelveLabs key and no real
API spend.

### Real videos, with a TwelveLabs key

1. Open **Settings**, paste your **TwelveLabs API key**, save. Validated against TwelveLabs, then
   encrypted at rest server-side; the browser only ever sees a masked preview.
2. Create a **campaign**: brief, master prompt, policy toggles, profanity tolerance, linked upload
   bucket. Testing with the sample videos below? [`docs/sample_videos/campaign_config.md`](docs/sample_videos/campaign_config.md)
   has the exact brief and master prompt they were verified against, paste both in as-is.
3. Upload a video, or drop one in the linked bucket. Background sync picks it up within 30 seconds.
4. Watch the live stages as the real pipeline runs, then the verdict, evidence timeline, and chat.

[`docs/sample_videos/`](docs/sample_videos) has one clip per verdict,
upload any of them and see how ClearFrame works.

## Using it for your own policies

Every policy lives in [`backend/config/policies.yaml`](backend/config/policies.yaml): GARM-mapped
categories (hate/harassment, drugs/illegal, profanity, unsafe usage, medical claims), each with a
`block_at` and `review_at` severity. Add, drop, or move a threshold, that is a config edit, and
`make eval` tells you immediately if the change broke a labeled case.

Each campaign can also set its own profanity tolerance, relevance threshold, and master prompt on
top of that shared taxonomy, right from the campaign creation form, so a strict pharma-adjacent
brand and a relaxed lifestyle brand run side by side, no code touched either way.

## What's done, what's not

**Working today:** the full pipeline end to end, mock or live; a three-pane reviewer console;
human override logged to an audit trail; per-campaign policy config; Supabase Postgres and Storage
in place of SQLite and local disk; CI running the unit tests and the eval set on every push.

**Not production-ready, and I'm not going to pretend otherwise:**
- No auth or per-advertiser tenancy, anyone who can reach the API sees every campaign.
- No durable job queue. Processing runs on a background thread in the same process; a server
  restart mid-job used to leave that review stuck showing "processing" forever. I hit this myself,
  fixed it to fail loudly instead, but the real fix, a queue, is not built yet.
- CORS is wide open. Fine for a local demo, not for anything public.
- The eval set is 16 hand-authored cases, a real regression gate, not proof of finished coverage.
  It checks the decision engine, not whether Pegasus actually sees the violation in a real video,
  that needs labeled real footage and is a harder, separate problem. A first slice of that exists:
  [`backend/eval/perception_truth.yaml`](backend/eval/perception_truth.yaml) records what each demo
  video is known to contain and [`perception_eval.py`](backend/eval/perception_eval.py) scores the
  pipeline's real results against it (verdicts, catch rate, false flags), a
  smoke test over a handful of videos, honestly labeled as such, not a benchmark. One
  representative live run is in [`docs/real_run_example.json`](docs/real_run_example.json) and
  [the screenshot](docs/real_run_example.png): a live Pegasus call catching an on-screen "clinically
  proven to clear acne" claim at the exact second it appears, timestamped BLOCK, not a fixture.

[`deployment/README.md`](deployment/README.md) has what a real deployment needs on top of this.

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

Data and storage are config-swappable: set `DATABASE_URL` for Postgres, `SUPABASE_*` for Storage,
no code change (see [Configuration](#configuration) below). Not just a theoretical option, I've
run this end to end against a real Supabase project, Postgres and Storage both, with real uploads
flowing through the linked bucket.

Marengo indexes every video, backs reviewer-driven search, and sharpens evidence timestamps:
Pegasus's timestamps are generated estimates, often off by a second or two, so each finding's
evidence text is searched back against the index, and when a matching clip is found the evidence
window is built from Marengo's measured boundaries instead of the estimate (when none is found,
the estimate with padding is used). Marengo does not score or corroborate findings, its `/search`
endpoint stopped returning a numeric score in this API version, so relevance and findings both
come from the Pegasus pass.

Pegasus 1.2 is what runs today. Pegasus 1.5 is out now with a larger context window and no
pre-indexing step, the natural next upgrade, not yet done.

<details>
<summary><h3>Project structure</h3></summary>

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
│   └── tests/                 # unit tests: decision engine, Marengo refinement, JSON parsing
├── frontend/
│   └── src/ClearframeApp.jsx  # the three-pane reviewer console, single file by design
├── docs/                      # architecture diagrams, design doc, screenshots
└── deployment/                # docker-compose, Render blueprint, AWS App Runner + diagram
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

## Testing and evaluation

None of this runs when a video is processed. It's a safety net over the *codebase*: on every
`git push` or PR to `main`, GitHub spins up a clean machine and runs the same commands below
([workflow](.github/workflows/ci.yml)); a code change that breaks a rule fails the build before
it lands on `main`.

```bash
make test     # every unit test file: decision engine, Marengo refinement, JSON parsing (22/22)
make eval     # scores the decision engine against the labeled set (the real correctness check, see below)
make demo     # runs the four sample creatives through the pipeline, writes an HTML report
```

`make test` checks that the rules in `decision.py`, the Marengo evidence-refinement logic, and the
JSON-repair layer each behave the way their code says they do, against fixed, synthetic inputs, no
video, no TwelveLabs call. `make demo` is for looking at output without opening the UI, four
verdicts with evidence, in one HTML file. `make eval` is the one that matters most: it scores the
decision engine against the labeled set and reports a confusion matrix, per-policy
precision/recall, and the two errors that actually cost something, *false blocks* (hurt the
advertiser) and *missed flags* (hurt brand safety). 16/16 today
([full report](backend/eval/REPORT.md), [how it works](backend/eval/README.md)).

One more script, outside `make` and not in CI: `python eval/perception_eval.py` scores real
pipeline results against known ground truth for the four sample videos, catch rate and timestamp
accuracy, not the decision rules. Manual only, see [What's done, what's not](#whats-done-whats-not)
for what it checks and why.

## Deployment

This is a starting blueprint, not a finished infra package. [`deployment/README.md`](deployment/README.md) covers two paths: quick (Vercel + Render) and cloud (AWS
App Runner, S3, CloudFront), including the one change that matters when scaling past a single
backend instance.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: open an issue, branch, keep changes small and
tested, and run `make test` before a PR.

## License

[MIT](LICENSE)

---

<p align="center">Created and maintained by <a href="https://www.linkedin.com/in/subashn/">Subash Natarajan</a></p>
