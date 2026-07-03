# Quick Deploy: Vercel + Render

The fastest way to get a live ClearFrame URL: frontend on Vercel, backend on Render, connected by
one environment variable. This is the detailed, step-by-step version of Path 1 in
[`deployment/README.md`](README.md).

## 1. Prerequisites

- A [Vercel](https://vercel.com) account (free tier is fine).
- A [Render](https://render.com) account (free tier is fine, with the cold-start caveat below).
- A GitHub account with this repo forked or accessible to both platforms.
- A [TwelveLabs](https://www.twelvelabs.io/) API key, optional. Without one the backend runs in
  mock mode against the bundled fixtures, real end-to-end plumbing, no real video analysis.
- Optional: a [Supabase](https://supabase.com) project, if you want real Postgres and real object
  storage instead of the defaults (SQLite on Render's ephemeral disk, local disk for uploads).
  Skip this for a demo; use it if you want data to survive a redeploy.

Nothing else needs installing locally for this path. You only need `git` to push to the repo both
platforms watch.

## 2. Backend on Render

### 2.1 Create the Blueprint

1. In the Render dashboard, click **New > Blueprint**.
2. Connect the GitHub repo (grant Render access if this is the first time).
3. Render asks for the Blueprint file path. **This is the step people get wrong**: Render only
   auto-detects a `render.yaml` sitting at the repo root. This repo's Blueprint lives at
   `deployment/render.yaml`, so you must set the path explicitly, either in the "Advanced" option
   during creation, or on the Blueprint's **Settings** page after it's created if Render already
   created one against the wrong (missing) file.
4. Confirm. Render reads [`deployment/render.yaml`](render.yaml) and shows you one service to
   create: `clearframe-api`.

What that file actually specifies, so you know what you're approving:

```yaml
services:
  - type: web
    name: clearframe-api
    runtime: python
    rootDir: backend
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn api:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /api/health
```

`rootDir: backend` resolves relative to the repo root, not relative to the Blueprint file's own
location, so it correctly points at the `backend/` folder even though the Blueprint file itself
lives one level down in `deployment/`. Render will run `pip install -r requirements.txt` from
inside `backend/`, then start the service with `uvicorn api:app --host 0.0.0.0 --port $PORT`.

### 2.2 Set environment variables

The Blueprint declares five variables with `sync: false`, meaning Render will prompt you to fill
each one in in the dashboard instead of hardcoding a value in the YAML (secrets shouldn't live in
a committed file). One variable, `TL_BASE_URL`, is already set with a real value and needs no
action from you.

| Variable | Required | What to put in |
|---|---|---|
| `TL_API_KEY` | No | Your TwelveLabs API key. Leave blank to run in mock mode against bundled fixtures. |
| `TL_BASE_URL` | Already set | `https://api.twelvelabs.io/v1.3`, comes pre-filled from the Blueprint, don't change it. |
| `DATABASE_URL` | No | Postgres connection string. Leave blank to use local SQLite on Render's disk. |
| `SUPABASE_URL` | No | Only if using Supabase Storage for uploads. e.g. `https://[project].supabase.co`. |
| `SUPABASE_SERVICE_KEY` | No | Supabase service_role key (Project Settings > API). Server-side only, never expose to the frontend. |
| `SUPABASE_BUCKET` | No | The Storage bucket name you created in Supabase, e.g. `creatives`. |

If you're only after a quick demo, leave all six blank/default and skip straight to deploying:
mock mode, SQLite, local disk, all work with zero configuration.

If you want real perception, set `TL_API_KEY`. If you want a database that survives redeploys
(Render's free-tier disk is ephemeral), set `DATABASE_URL` to a Supabase Postgres connection
string (Supabase dashboard: Project Settings > Database > Connection string, prefer the pooled
"Transaction" or "Session" pooler URI, not the direct connection). If you want uploaded creative
files to persist the same way, also set the three `SUPABASE_*` variables.

### 2.3 Deploy and get the URL

Click **Apply** (or **Create New Resources**, depending on the Render UI version you land on).
Render builds and deploys the service. First deploy typically takes a couple of minutes. You'll
get a URL shaped like:

```
https://clearframe-api.onrender.com
```

### 2.4 Verify the backend deploy

```bash
curl https://clearframe-api.onrender.com/api/health
```

Expected shape:

```json
{"ok": true, "mock": true, "db": "sqlite", "storage": "local"}
```

`mock` is `true` when no TwelveLabs key is connected (via `TL_API_KEY` or the Settings UI), `false`
once one is. `db` reads `"sqlite"` by default or `"postgres (supabase)"` once `DATABASE_URL` is
set. `storage` reads `"local"` by default or `"supabase"` once all three `SUPABASE_*` variables are
set. If `curl` hangs or times out on the first request, that's the free-tier cold start (see
Known limits below); a second request a few seconds later should return normally.

## 3. Frontend on Vercel

### 3.1 Import the project

1. In Vercel, **Add New > Project**, import the same GitHub repo.
2. Vercel reads [`vercel.json`](../vercel.json) at the repo root automatically (it's intentionally
   kept there, not moved into `deployment/`, because Vercel's monorepo convention expects config
   at the project's Root Directory, which defaults to the repo root). No manual build settings
   needed. The file specifies:

```json
{
  "buildCommand": "cd frontend && npm install && npm run build",
  "outputDirectory": "frontend/dist"
}
```

Leave Vercel's own "Root Directory", "Build Command", and "Output Directory" project settings on
their defaults; `vercel.json` overrides them for you.

### 3.2 Set the API base URL

In the Vercel project's **Settings > Environment Variables**, add:

| Key | Value |
|---|---|
| `VITE_API_BASE` | `https://clearframe-api.onrender.com` (your actual Render URL from step 2.3, no trailing slash) |

This is how the frontend actually finds the backend. In
[`frontend/src/ClearframeApp.jsx`](../frontend/src/ClearframeApp.jsx):

```js
const API_BASE = (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_API_BASE) || "http://localhost:8000";
```

Every API call in the app (`fetch(\`${API_BASE}/api/...\`)`) is built off this constant. Vite
inlines `import.meta.env.VITE_API_BASE` at build time, so the variable has to be set in Vercel
*before* the build runs, not just at runtime; if you add or change it after a deploy, you need to
trigger a new deploy for it to take effect. If it's unset, the built app falls back to
`http://localhost:8000`, which won't exist in production, and the app will silently drop into its
built-in offline demo mode (see Verification below).

### 3.3 Deploy

Click **Deploy**. Vercel builds the frontend and serves the static output from its CDN. No backend
runs on Vercel; every API call from the deployed frontend goes straight to the Render URL you set
above.

## 4. Verification checklist

Run through all of these after both deploys finish. Don't stop at "the page loads": the frontend
is built to look complete even with zero backend connectivity, so a working-looking UI is not
proof the wiring is correct.

1. **Backend health.**
   ```bash
   curl https://clearframe-api.onrender.com/api/health
   ```
   Confirm you get back `{"ok": true, ...}`, not a timeout or a 502.

2. **Frontend loads.** Open the Vercel URL in a browser. The three-pane reviewer console should
   render.

3. **Frontend is actually talking to the real backend, not its offline demo fallback.** Open
   browser dev tools, Network tab, reload the page. You should see requests going out to
   `https://clearframe-api.onrender.com/api/...` (not `localhost:8000`) and returning `200`. The
   app has a silent fallback: if the initial campaign fetch fails for any reason, it swallows the
   error and renders a self-contained local demo seed instead, so a blank Network tab or a run of
   failed requests, with the UI still looking populated, means it fell back, not that it worked.

4. **Create a real test campaign.** In the UI, create a campaign, upload a short video (or, if
   `TL_API_KEY` is unset, exercise the mock pipeline). Confirm a review row appears, moves through
   its processing stages, and lands on a verdict (APPROVE / REVIEW / BLOCK). This proves the full
   round trip: frontend to Render backend to (mock or real) TwelveLabs to the decision engine and
   back.

5. **Confirm persistence matches what you configured.** If you left `DATABASE_URL` unset, restart
   the Render service (Manual Deploy) and confirm data is gone (expected with SQLite on ephemeral
   disk). If you set `DATABASE_URL` to Supabase, confirm the campaign survives a redeploy.

## 5. Environment variables reference

| Variable | Where it's set | Required | Purpose |
|---|---|---|---|
| `TL_API_KEY` | Render | No | TwelveLabs API key. Unset means mock mode (bundled fixtures, no real API spend). Can also be set later from the in-app Settings panel, encrypted at rest server-side. |
| `TL_BASE_URL` | Render (pre-filled by `render.yaml`) | Yes (already set) | TwelveLabs API base URL, `https://api.twelvelabs.io/v1.3`. No reason to change it. |
| `DATABASE_URL` | Render | No | Postgres connection string (Supabase or otherwise). Unset means local SQLite (`clearframe.db`), which does not survive a Render redeploy. |
| `SUPABASE_URL` | Render | No | Supabase project URL, e.g. `https://[project].supabase.co`. Needed only for Supabase Storage. |
| `SUPABASE_SERVICE_KEY` | Render | No | Supabase `service_role` key. Server-side only; never put this in the frontend. Needed only for Supabase Storage. |
| `SUPABASE_BUCKET` | Render | No | Name of the Supabase Storage bucket for uploaded creatives, e.g. `creatives`. Needed only for Supabase Storage. |
| `VITE_API_BASE` | Vercel | Yes, for a working deploy | The Render backend's public URL. Baked into the frontend build at build time by Vite; without it the app defaults to `http://localhost:8000` and falls back to offline demo mode in production. |

`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `SUPABASE_BUCKET` are a set: `storage.enabled()` in the
backend only turns on Supabase Storage when all three are present, otherwise uploads stay on local
disk regardless of how many of the three you set.

## 6. Rollback

**Render.** Open the `clearframe-api` service, go to the **Events** or **Deploys** tab, find the
last known-good deploy, and click **Redeploy** (or the equivalent "rollback to this deploy"
action in your Render UI version). Render keeps deploy history per service, so this doesn't
require a new git push, it redeploys the exact previous build.

**Vercel.** Open the project's **Deployments** tab, find the last known-good deployment, and use
**Promote to Production** (older Vercel UIs call this "Instant Rollback"). This repoints the
production domain at that build immediately, no rebuild needed.

Neither rollback undoes data changes in Postgres if you're using `DATABASE_URL`; this is a code
rollback, not a database rollback.

## 7. Known limits of this path

- **SQLite by default.** Unless you set `DATABASE_URL`, the backend uses a local SQLite file on
  Render's disk. Render's free and starter web service disks are not guaranteed persistent across
  deploys or restarts, treat this as demo-only storage.
- **Render free-tier cold starts.** A free-tier (or low-tier) Render web service spins down after
  a period of inactivity and takes on the order of tens of seconds to serve the next request. The
  first `curl` or page load after idle time will be slow; this is expected, not a bug.
- **No autoscaling.** `render.yaml` provisions a single `starter` plan instance. Traffic beyond
  what one instance handles will queue or fail; there's no horizontal scaling configured on this
  path.
- **CORS is wide open.** `backend/api.py` sets:
  ```python
  app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
  ```
  Any origin, any method, any header can call this API. That's fine for a demo you're the only one
  hitting, but it means there's no origin restriction protecting the API once it's public; treat
  the deployed URL as effectively open to anyone who finds it, since there's also no auth layer in
  front of it (see the root [README](../README.md#whats-done-whats-not) for the full list of
  what's not production-ready yet).
- **No auth, no tenancy.** Anyone with the Render URL can see every campaign and every review
  through the API. Don't put real, sensitive creative content through a publicly reachable deploy
  of this path.
