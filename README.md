# Clearframe

**Brand-safe clearance for creator video ads.**

Clearframe is an automated ad compliance gate for a social platform that promotes
creator beauty videos as paid ads. For every submitted creative it returns an
**APPROVE / REVIEW / BLOCK** decision, an auto-generated description, and
**timestamped evidence** for every reason behind the call. It uses TwelveLabs for
video perception and a deterministic policy engine for the verdict.

> The model perceives. The engine decides.
>
> TwelveLabs understands what happens in the video across visuals, speech and
> on-screen text. A separate, deterministic policy engine turns that into the
> verdict. No language model makes the final compliance call on its own, because
> in an ads system a wrong auto-block on a large advertiser is a revenue and
> trust incident, not just a bug.

## What is here

```
clearframe/
  backend/            Python compliance pipeline + FastAPI service
    src/              perception, decision engine, pipeline (the core logic)
    api.py            thin async API: bulk upload, status, human override
    config/           GARM-mapped policy taxonomy + campaign brief (YAML)
    fixtures/         recorded TwelveLabs responses for four demo scenarios
    demo/             CLI that runs the pipeline and writes an HTML report
    tests/            decision-engine unit tests
  frontend/           React + Vite reviewer UI
    src/ClearframeApp.jsx   bulk upload, batch dashboard, evidence-timeline detail
    src/Clearframe.jsx      focused single-screen reviewer
  docs/               design document (PDF + HTML)
  docker-compose.yml  optional: run API + web together
  Makefile            common commands
```

## Quickstart

Everything runs in **mock mode** out of the box. No TwelveLabs key required, so
the demo is safe to run live.

```bash
# backend
cd backend
pip install -r requirements.txt
python tests/test_decision.py      # 5/5 pass
python -m demo.run_demo --html     # decisions + demo/report.html
uvicorn api:app --reload           # API on http://localhost:8000

# frontend (separate terminal)
cd frontend
npm install
npm run dev                        # UI on http://localhost:5173
```

Or use the Makefile from the repo root: `make install`, `make test`,
`make demo`, `make api`, `make web`.

## How a decision is made

1. **Relevance gate** (cheap filter): a Marengo search of the campaign brief
   against the creative. Off-brief clickbait is rejected before deep analysis.
2. **Reasoning pass** (Pegasus `/analyze` with a JSON schema): the 2 to 5
   sentence description, the on-brief judgement, and structured policy findings.
3. **Evidence pass** (Marengo `/search` per-policy probes): timestamped,
   confidence-scored clips that corroborate specific known-bad patterns.
4. **Decision engine** (deterministic, config-driven): combines the signals into
   APPROVE / REVIEW / BLOCK with reasons and evidence. The most serious calls
   require the reasoning and evidence passes to agree.

Confidence and human-in-the-loop: two-source agreement is high confidence, a
single source is medium. Any automated APPROVE or BLOCK below the configured
minimum confidence is downgraded to REVIEW so a human looks at it.

## Policy taxonomy

Policies live in `backend/config/policies.yaml`, mapped to the GARM Brand Safety
Floor and Suitability Framework: hate/harassment, drugs/illegal, profanity,
unsafe product usage, and medical/cosmetic claims, plus a campaign relevance
gate. Adding a category or changing a tolerance is a config edit, not a code
change. (GARM the organisation was disbanded in 2024, but its framework remains
the de facto standard; Clearframe adopts the framework, not the defunct body.)

## Real vs mock

The TwelveLabs integration in `backend/src/client.py` is written against the
documented v1.3 REST endpoints (`/tasks`, `/analyze`, `/search`) with real and
mock modes. Every network call has a fixture-backed mock so the full pipeline
runs in CI and in a demo without a key, upload latency or quota spend. Set
`TL_API_KEY` and point at real videos to run live.

## From prototype to product

What runs today: the full pipeline, a thin async API with bulk upload, and a
runnable reviewer UI, end to end in mock mode. What a deployed multi-tenant
product still needs: authentication, hosting, Postgres in place of SQLite, a real
queue and object storage in place of background tasks, monitoring, and
per-advertiser tenancy. None is hard; it is a few focused days, not a rewrite,
because the seams were kept clean.

See `docs/Clearframe_Design_Doc.pdf` for the full design, scale story, and
build-versus-buy analysis.
