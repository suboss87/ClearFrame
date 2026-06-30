# Plan: Campaigns + live pipeline progress

## Goal
- Rename **Upload → Campaign** (bulk + single upload + bulk processing live under a named campaign).
- **Keep the Review queue** dashboard and its upload button/icon.
- Add **real campaign grouping** (create/select a campaign, group videos, filter the queue by campaign).
- New headline feature: **real-time progress** — show the user what the backend is doing per video, stage by stage.
- Phase 1 = UI restructure in **demo mode**. Phase 2 = wire to live backend.

## The real pipeline stages (source of truth for progress)
From `backend/src/pipeline.py`, one video flows through:
1. `upload_and_index`  -> **Uploading**
2. `wait_for_index`    -> **Indexing** (TwelveLabs builds embeddings; ~30s live)
3. `relevance_score`   -> **Relevance gate** (Marengo vs campaign brief)
4. `run_analysis`      -> **Analyzing** (Pegasus structured reasoning)
5. `run_search_probes` -> **Gathering evidence** (Marengo per-policy probes)
6. `evaluate`          -> **Deciding** (deterministic engine)
7. done                -> **Decided** (APPROVE / REVIEW / BLOCK)

Stage enum: QUEUED -> INDEXING -> RELEVANCE -> ANALYZING -> EVIDENCE -> DECIDING -> DONE | FAILED

---

## Phase 1 — Frontend restructure (demo mode, no backend needed)  ✅ DONE & browser-verified

### 1A. Navigation
- [x] Tab "Upload" -> "Campaign" (Layers icon). Kept "Review queue" tab.
- [x] Kept the Upload button/icon inside the Review queue header (routes to Campaign).

### 1B. Campaign concept (demo: in-memory)
- [x] campaigns model `{ id, name, brief, createdAt }`; reviews carry `campaignId`.
- [x] Campaign view: create a new campaign (name + brief) or open an existing one (CampaignPicker).
- [x] Every uploaded video is tagged with its `campaignId`.

### 1C. Live progress (the headline)
- [x] PIPELINE = the 5 real stages with plain-language detail lines.
- [x] Per-video stage stepper: done / active (spinner) / pending / skipped states.
- [x] Off-brief creatives visibly skip Analyzing + Evidence at the relevance gate.
- [x] Campaign aggregate: "X of Y decided", progress bar, running verdict tally.
- [x] Demo simulates per-stage timing, staggered across files (verified mid-flight).

### 1D. Review queue
- [x] Added Campaign column + campaign filter dropdown (alongside verdict filter).
- [x] File shown as a subtitle under the creator to make room for Campaign.

## Phase 1.5 — Merged three-pane console (NotebookLM-style)  ✅ DONE & browser-verified
- [x] Replaced tabbed shell with single-screen three-pane: rail | center | decision.
- [x] Left rail = search + filters + campaign groups (collapsible, tally dots) + live jobs.
- [x] Search: empty = grouped browse; typing = flat ranked results, deep match (creator/file/campaign/reasons/policy labels).
- [x] In-flight creatives always visible; selecting one shows its live pipeline stepper in the center.
- [x] Keyboard ops: / search, j/k move, a/b decide, u upload, Esc back. Hint bar in rail footer.
- [x] Upload modal: pick/create campaign → drop 1+ files → streams into queue, processes live.
- [x] Auto-selection keeps a valid item selected (fixes StrictMode id drift).

## Phase 1.6 — Rail at scale (100+ videos)  ✅ DONE & browser-verified
- [x] Seeded ~84 creatives across 3 campaigns + Unsorted (90 after a Drive sync demo).
- [x] Campaigns = collapse-by-default folders; first folder open on load.
- [x] Per-folder verdict bar (true block/review/approve composition) + count.
- [x] "Needs attention" default filter (Block + Review); All/verdict chips too.
- [x] Unsorted inbox bucket for single / ad-hoc uploads (no campaign needed).
- [x] Processing section pinned to top of rail (visible even with all folders collapsed).
- [x] "+N more" per folder caps DOM at 14 rows (react-window can replace later).
- [x] New Campaign footer button → opens popup in new mode.
- [x] Drive sync MOCK: "Connect Google Drive folder (simulated)" → streams 6 clips in.
- [x] Fixed: collapsing a folder no longer clears the center (selection valid by id).

## Phase 1.7 — UX refinements  ✅ DONE & browser-verified
- [x] Filter chips compact, single line: Needs[35] · All · Block · Review · Approve.
- [x] Themed thin scrollbar (.cf-scroll) replacing the chunky default, on all 3 panes.
- [x] User profile (Subash Natarajan) + Settings modal at the bottom of the rail.
- [x] Collapsible left rail (header toggle) → center video gets full width.
- [x] Chat-with-video panel below the description (TwelveLabs/Pegasus branded);
      demo answers synthesised from decision data; live = POST /api/reviews/{id}/ask.
- [x] Right decision panel reviewed — left as-is (complete for the decision).

## Phase 1.8 — UX refinements II  ✅ DONE & browser-verified
- [x] Removed the keyboard-shortcut hint bar (shortcuts still work).
- [x] Chat docked at the bottom of the center pane; input pinned at bottom, answers populate above.
- [x] Draggable resize handle between video and chat (verified 387→524px).
- [x] Compact filter: amber ⚠ + count (e.g. "⚠ 35"), tooltip explains; one line.
- [x] Post-decision outcome card: after Approve/Block, shows what happens next
      (cleared/removed, queued, creator notified, audit-logged) + Undo. Fills the panel.

## Phase 1.9 — Center layout + logo  ✅ DONE & browser-verified
- [x] Flipped center order: description on top, video in middle, chat docked at bottom.
- [x] Removed the dead gap: top region fits content, chat fills remaining (504+160=664, exact).
- [x] Chat scrolls when messages stack + auto-scrolls to latest (verified 157>51, atBottom).
- [x] Resize handle now adjusts the top region height; chat fills the rest (no gap at any size).
- [x] Removed the a/b key labels from the Approve/Block buttons.
- [x] New solid, minimal logomark (frame + clearance check); wordmark "ClearFrame".

## Phase 1.10 — Header, toggle, logo  ✅ DONE & browser-verified
- [x] Moved the rail collapse toggle into the search row (right side).
- [x] Header is now just logo + wordmark; expand button appears there only when collapsed.
- [x] Redesigned logo: camera viewfinder (frame) + clearance check, emerald→cyan gradient. Wordmark Clear+Frame two-tone.
- [x] Collapse/expand cycle verified (300 ↔ 0).

## Phase 1.11 — Settings key, polish  ✅ DONE & browser-verified
- [x] TwelveLabs API key field in Settings → Integrations: masked input, reveal toggle,
      Save → masked preview (tlk_••••••••b510) + Connected pill, Replace/Remove.
      NOTE: demo stores in localStorage; real product = backend, HTTPS, encrypted at rest.
      The key field is the entry point — Phase 2 backend must CONSUME it to actually call TwelveLabs.
- [x] Brighter logo gradient (#4ade80 → #22d3ee); Upload button flipped to outline (border + bright text).
- [x] Campaign folder rows redesigned to a single tight line (name + bar + count); no wasted space.
- [x] Escape now closes the Settings modal too.

## Phase 2 — Backend LIVE  ✅ DONE & verified (mock path end-to-end; key validated against real TwelveLabs)
- [x] Researched + verified current TwelveLabs v1.3 API (endpoints, models, shapes).
- [x] db.py: SQLite campaigns + reviews(campaign_id, stage, video_id, human_decision) + settings.
- [x] keystore.py: Fernet-encrypted API key at rest; masked preview only to client.
- [x] client.py: corrected real calls (analyze video_id + response_format wrap; pegasus1.2 index;
      marengo3.0 audio→transcription); added create_index, validate(), ask().
- [x] pipeline.py: on_stage callback + per-campaign brief + returns video_id.
- [x] api.py: /health, /settings(+key save/delete, validated), /campaigns, /reviews/upload,
      /reviews/{id} (stage), /decision, /ask. Builds client from stored key (mock if none).
- [x] Frontend: health-gated LIVE mode; loads campaigns/reviews from backend; real upload+poll,
      real chat (/ask), real decisions (/decision), key save → encrypted backend. Demo fallback.
- [x] Verified live via browser: create campaign → upload → BLOCK verdict; chat 200; decision persisted;
      bad key rejected by real TwelveLabs (401→400). Fixed mock-index validation-bypass bug.

## Phase 2.1 — Supabase Postgres support  ✅ DONE (SQLite verified; PG path reachable, needs creds to fully run)
- [x] db.py: dual backend — SQLite by default, Postgres (Supabase) when DATABASE_URL is set.
- [x] Abstracted the two dialect diffs: placeholder (?/%s) + upsert (ON CONFLICT … excluded.value).
- [x] init() auto-creates tables (IF NOT EXISTS) → fresh Supabase project provisions on first run.
- [x] psycopg2-binary dep; .env.example documents DATABASE_URL; /api/health reports the active db.
- [x] Verified: SQLite end-to-end (verdict BLOCK); Postgres branch activates + psycopg2 connects.
- [x] CONNECTED to the user's real Supabase project + verified end-to-end:
      tables auto-created; campaign+upload+verdict(BLOCK)+chat+decision all persist to Postgres;
      frontend live, reads/writes Supabase. db.backend_name()="postgres (supabase)".
- [x] PERF: added ThreadedConnectionPool + killed N+1 in /campaigns → 11.7s → 0.78s (~15x).
- [ ] SECURITY: user's DB password was pasted in chat → ROTATE it (Supabase → Database → reset password), update DATABASE_URL.
- [ ] Video Storage: still needs the SECRET key (sb_secret_/service_role); publishable key can't write Storage.

## Phase 2.2 — Live key + fixes  ✅ DONE
- [x] Moved TwelveLabs API key to the TOP of Settings (was below the fold → "no option").
- [x] Surfaced real backend error in the UI toast (was a generic "rejected").
- [x] FIXED key-save bug: ensure_index tried to CREATE a duplicate "clearframe-index" (400);
      now find_index reuses the existing one. Real key validates + connects (mock=false).
- [x] Verified: user's real key (tlk_…E9XE) → connected, reused index 6a432494…, UI shows Connected.
- [ ] SECURITY: TwelveLabs key + DB password are in chat history → rotate both after the demo, re-save.
- [ ] Currently on SQLite (Supabase project down). Re-enable DATABASE_URL + re-save key when Supabase is healthy.

## Phase 2.3 — Simplified upload + Supabase as input  ✅ DONE (storage env-gated, needs secret key to activate)
- [x] Header "Upload" = single quick upload → file picker → Unsorted (no campaign modal).
- [x] "New Campaign" = bulk path (name + drop many). Removed Google Drive section (too much formality).
- [x] Backend storage.py: upload to Supabase Storage + signed URL → TwelveLabs fetches from your bucket.
      Files organized as Clearframe/{campaign_id}/{review_id}_{file}. Falls back to local disk.
- [x] /api/health reports storage: "supabase" | "local". Currently "local" (no secret key).
- [ ] To activate Supabase input: Supabase project healthy + SUPABASE_SERVICE_KEY in .env.
- Decision: drop Google Drive; Supabase Storage = single input + storage + DB layer.

## To go live on real videos (user action)
- [ ] `make api` + `make web`, open :5173 → Settings → paste real TwelveLabs key → upload real videos.
- [ ] (Optional, real) Drive sync = Google OAuth; production = Postgres/queue/object-store/auth.
- [ ] Build all of this in MOCK mode first (no API key needed); key only flips it live at the end.
- [ ] campaigns table + endpoints; reviews gain campaign_id + stage columns.
- [ ] on_stage callback in review_video() → real live progress via apiPoll.
- [ ] /api/reviews/{id}/ask → TwelveLabs Pegasus open-ended analyze (real chat-with-video).
- [ ] persist human decisions/outcomes.
- [ ] verify client.py real calls against live TwelveLabs v1.3 (base URL, model names, shapes).
- [ ] Drive sync: needs Google Cloud OAuth creds (separate from TwelveLabs).
- [ ] Production: auth, hosting, Postgres, queue, object storage, monitoring, tenancy.

### 2A. Data model (SQLite, then Postgres later)
- [ ] `campaigns(id, name, brief, created_at)`
- [ ] `reviews` add columns: `campaign_id`, `stage`, `stage_detail`.

### 2B. Progress reporting
- [ ] `review_video(..., on_stage=callback)` — pipeline calls `on_stage(stage)`
      after each stage; `api._run_pipeline` writes `stage` to the DB.
- [ ] `apiPoll` reads `stage` each tick and drives the same stepper UI live.
- [ ] (Enhancement) SSE endpoint `/api/reviews/{id}/events` to push stage changes
      instead of polling. Polling first; SSE if we want true push.

### 2C. Campaign endpoints
- [ ] `POST /api/campaigns` (name, brief) ; `GET /api/campaigns` (list + rollup)
- [ ] `GET /api/campaigns/{id}` (detail + its reviews)
- [ ] `POST /api/campaigns/{id}/upload` (bulk into a campaign) ; existing upload gains `campaign_id`.

## Verification
- [ ] Phase 1: `npm run build` clean; click through Campaign -> progress -> queue in browser.
- [ ] Phase 2: `python tests/test_decision.py` still 5/5; live upload shows stages advancing.

## Key design decisions
- Progress via **stage column + polling** (fits the existing async-poll contract); SSE is an opt-in enhancement, not required.
- Single vs multiple upload is **one flow** (drop 1 or many) — no separate single-upload tab; the backend already treats single as bulk-of-one.
- Campaign is a **first-class entity**, not a label (your call): needs the DB + endpoints above.
