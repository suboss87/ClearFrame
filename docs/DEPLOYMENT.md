# Deployment

ClearFrame is two independently deployable pieces: a static React frontend and a stateless
FastAPI backend. Two paths are set up here: a fast one for standing up a live demo in minutes,
and an AWS-native one that shows how this would actually run in production. Both are meant as
**working starting points**, not turnkey one-click deploys: you still need your own accounts,
API keys, and (for AWS) a few resources provisioned once.

## Path 1: Vercel + Render (fastest to a live URL)

Good for sharing a live demo link. Frontend on Vercel, backend on Render, connected with one
environment variable.

**Backend, Render**
1. Create a new **Web Service** on [Render](https://render.com), pointing at this repo.
2. Render picks up [`render.yaml`](../render.yaml) automatically (root `rootDir: backend`,
   `uvicorn api:app --host 0.0.0.0 --port $PORT`).
3. Set `TL_API_KEY` in the Render dashboard (leave unset to run in mock mode against the bundled
   fixtures). Optionally set `DATABASE_URL` for Postgres, or `SUPABASE_URL` /
   `SUPABASE_SERVICE_KEY` / `SUPABASE_BUCKET` for Supabase-backed storage, see
   [`backend/.env.example`](../backend/.env.example) for the full list.
4. Render gives you a URL like `https://clearframe-api.onrender.com`. Confirm it is live:
   `curl https://clearframe-api.onrender.com/api/health`.

**Frontend, Vercel**
1. Import this repo into [Vercel](https://vercel.com). [`vercel.json`](../vercel.json) sets the
   build command (`cd frontend && npm install && npm run build`) and output directory
   (`frontend/dist`).
2. Set the environment variable `VITE_API_BASE` to the Render URL from above.
3. Deploy. Vercel serves the built static assets from its CDN; API calls go straight to Render.

This path has no autoscaling, cold starts on Render's free tier, and SQLite by default, fine for
a demo, not for production load.

## Path 2: AWS (production-shaped)

The pattern used at higher volume: a container behind App Runner, Postgres and object storage
managed, secrets out of the codebase, and a build that only ships an image once the eval harness
passes. See [`clearframe_aws_deployment.excalidraw`](clearframe_aws_deployment.excalidraw) for
the full topology.

```
Creator / Compliance team
        |
        v
CloudFront + S3  (static frontend build)
        |  API calls (HTTPS)
        v
App Runner  (1 container: pre-check + TwelveLabs client + decision engine + bucket sync)
        |                     |                      |
        v                     v                      v
  RDS Postgres          S3 (video bucket)     Secrets Manager
  reviews, campaigns,   creator uploads       TL_API_KEY, DB creds
  audit trail
        |
        v
  TwelveLabs API (external, outbound only)

CI/CD:  GitHub Actions -> run tests + eval harness -> gate on 16/16 -> build image -> push to ECR
        -> App Runner auto-deploys the new image
```

**What's provided as a starting artifact**
- [`backend/Dockerfile`](../backend/Dockerfile): the image App Runner runs.
- [`aws/apprunner-service.json`](../aws/apprunner-service.json): an App Runner
  `create-service` definition, image sourced from ECR, secrets sourced from Secrets Manager
  (`TL_API_KEY`, `DATABASE_URL`, `SUPABASE_SERVICE_KEY`), health check on `/api/health`.

**What you provision once, by hand, before this applies**
1. An ECR repository (`clearframe-api`) and push the built image to it.
2. An `AppRunnerECRAccessRole` IAM role App Runner can assume to pull from ECR.
3. An RDS Postgres instance (or reuse Supabase's Postgres, same `DATABASE_URL` shape either way).
4. Secrets in Secrets Manager, referenced by ARN in `aws/apprunner-service.json`.
5. Point `AutoDeployments` at the ECR repo so a new `:latest` push rolls out automatically.

**The one scaling caveat worth being honest about**, called out on the diagram itself: bucket
sync (polling creator buckets for new uploads) currently takes an in-process lock. That's correct
at one instance and would double-process uploads at two or more. Before scaling App Runner past
one instance, that lock needs to move to a Postgres advisory lock (a small, contained change:
`_SYNC_LOCK` in `backend/api.py` is the only place that takes it).

## Local development

Neither path above is needed for day-to-day work. `make install`, `make seed`, `make api` (port
`8000`), `make web` (port `5000`), everything runs in mock mode with no API key. See the root
[README](../README.md) and [CONTRIBUTING.md](../CONTRIBUTING.md).
