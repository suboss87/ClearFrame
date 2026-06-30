# ClearFrame — Solutions Engineering Take-Home

**Theme:** Ad Compliance & Brand Safety for Social Video Ads
**Scenario:** Global Makeup Brand Campaign
**Built with:** TwelveLabs (Marengo + Pegasus), FastAPI, React, Supabase

> **The model perceives. The engine decides.**
> TwelveLabs understands what happens in a video across visuals, speech, and on-screen
> text. A separate, deterministic policy engine turns that understanding into the verdict —
> because in an ads system, a wrong auto-block on a large advertiser is a revenue and trust
> incident, not just a bug.

---

## 1. What was asked

A large social platform earns its revenue from video ads. Advertisers increasingly promote
**creator videos as the ad creative itself**. Before a creator's beauty video can run as a paid
ad for a global makeup brand, the platform's **Ads Compliance team** must clear it —
**automatically and at scale**.

The system must:

| # | Requirement |
|---|-------------|
| 1 | **Filter off-brief submissions** — is the video actually about the campaign product? |
| 2 | **Evaluate compliance** across ≥5 policy categories (visuals, speech, on-screen text) |
| 3 | **Generate a 2–5 sentence video description** |
| 4 | **Return a decision** — APPROVE / REVIEW / BLOCK |
| 5 | **Provide timestamped evidence** explaining every decision |

Advertiser policy for this campaign: no hate/harassment, no drugs/illegal behavior, limited
profanity tolerance, must be on-brief, no unsafe or misleading product use (eye-area misuse,
medical claims), and **clear explanations** for anything blocked or reviewed.

Evaluation focus stated by the brief: **product thinking, technical clarity, demo storytelling.**

---

## 2. What we built — ClearFrame

ClearFrame is a **reviewer console for an Ads Compliance team**. A creator submits a video; the
system clears it end to end and hands the human a verdict they can trust, override, and explain.

### The core idea: perceive vs. decide

We deliberately split the system into two layers:

- **Perception (TwelveLabs).** One indexing pass builds a multimodal understanding of the clip.
  **Pegasus** reads visuals + speech + on-screen text and returns a structured analysis: a
  neutral description, an on-brief judgment, a 0–1 relevance score, and per-policy findings with
  severities and **timestamps**. **Marengo** powers semantic search/retrieval over the indexed
  video for reviewer-driven exploration.
- **Decision (deterministic engine).** A small, auditable policy engine (`decision.py` +
  `policies.yaml`) turns the model's findings into APPROVE / REVIEW / BLOCK by applying the
  advertiser's thresholds. **No LLM decides the verdict** — the model supplies evidence, the
  engine applies policy.

This separation is the product argument: model outputs drift and can't be unit-tested; **policy
must be deterministic, versioned, and explainable** because money and advertiser trust ride on it.

### How each requirement is met

| Requirement | How ClearFrame delivers it |
|-------------|----------------------------|
| **Off-brief filter** | Pegasus scores relevance (0–1) against the **campaign brief**; below threshold *and* judged off-brief → blocked at the relevance gate before any policy spend |
| **≥5 policy categories** | Hate/harassment, profanity, drugs/illegal, unsafe usage, medical/cosmetic claims — each with severity (none/low/med/high) and per-policy block/review thresholds |
| **Video description** | 2–5 sentence neutral description from Pegasus, shown on every review |
| **Decision** | APPROVE / REVIEW / BLOCK from the deterministic engine, with a confidence level |
| **Timestamped evidence** | Each finding carries the seconds it occurs at; the reviewer clicks a reason to jump the player to that moment |
| **Explainability** | Every verdict lists human-readable reasons + a full audit trail (who/what/when, auto and human actions) |

### Per-campaign governance (the product layer)

Compliance isn't one global ruleset — it's **per campaign**. At campaign creation the team sets a
**master prompt** (brief + flagging guidance), a **profanity tolerance** (Strict / Balanced /
Relaxed), a **relevance threshold**, which **policies** are on, and a **linked bucket** creators
drop videos into. That config is injected into relevance, perception, and decision at runtime — so
the same engine serves a strict pharma-adjacent campaign and a relaxed lifestyle one without code
changes.

### Workflow

System **auto-decides**; the human **only overrides**. An override asks for a comment; the
creator is notified automatically in the backend. This keeps the team at scale — they spend
attention on the REVIEW queue and edge cases, not on rubber-stamping clean approvals.

---

## 3. Why the outputs are trustworthy

- **Deterministic, versioned policy.** The verdict comes from `policies.yaml` thresholds, not a
  prompt. Change a threshold → re-run the eval → ship with confidence.
- **An offline eval harness.** 16 labeled cases run through the *real* decision engine in CI,
  reporting a confusion matrix and per-policy precision/recall/F1. Currently **16/16 (100%)**.
  This is how you catch policy drift before it reaches a live advertiser — the eval validates the
  engine **offline**; it is never in the runtime decision path.
- **Evidence, not vibes.** Every reason links to a timestamp the reviewer can watch. A decision
  you can't point at in the video isn't a decision you can defend to an advertiser.
- **Full audit trail.** Auto-decisions and human overrides are both logged with actor, action,
  comment, and time.
- **Human in the loop by design.** Low-confidence auto-calls route to REVIEW rather than acting.

> **Engineering honesty note:** Marengo 3.0's search API dropped numeric relevance scores
> mid-build. Rather than ship a silently-broken "relevance 0.00", we moved relevance and
> timestamped evidence onto Pegasus's multimodal analysis (which reads visuals + speech + text in
> one pass) and kept Marengo for reviewer-driven search. Adapting cleanly to an API contract
> change — with tests and eval still green — is itself part of the SE story.

---

## 4. How this scales in a real ads system

- **Ingestion at scale.** Creators drop videos into a per-campaign bucket (Supabase Storage); a
  background sweeper ingests new files automatically. A deterministic **pre-check** (duration,
  size, format, dedup-by-content-hash) runs *before* any TwelveLabs spend — off-brief and junk are
  filtered cheaply.
- **Spend discipline.** The off-brief relevance gate and the pre-check both exist to **protect
  compute and reviewer bandwidth** — exactly what an ads buyer cares about at volume.
- **Stateless pipeline, queue-ready.** Each review runs through the same staged pipeline
  (index → analyze → decide); in production the worker becomes a queue consumer resumed by a
  TwelveLabs webhook.
- **Postgres + object storage.** Runs on SQLite locally, Supabase Postgres + Storage in
  production — same code path.
- **Policy as configuration.** New campaigns, categories, and thresholds are config, not code.

---

## 5. How it's positioned & presented (demo storytelling)

**Positioning:** *ClearFrame is the brand-safety clearance gate that lets an Ads Compliance team
approve creator video ads automatically and at scale — with evidence they can defend to the
advertiser.* It is built **for the reviewer**, not as a model demo.

**The demo arc (≈5 minutes), one campaign, four contrast shots:**

1. **Set the stage** — open the *Lumiere Velvet Matte – Spring Launch* campaign. Show the master
   prompt + policies + relevance threshold. "This is the advertiser's contract, encoded."
2. **APPROVE** — a clean on-brief tutorial sails through. Read the auto-description; note the green
   verdict and high confidence. "No human touched this; that's the scale win."
3. **BLOCK (the hero)** — an on-brief clip with a **medical claim** ("clinically proven to cure
   acne"). Click the reason → the player jumps to the exact second the claim is spoken / on screen.
   "This is why it's trustworthy: every call points at the frame."
4. **REVIEW** — a clip with mild profanity under *Balanced* tolerance routes to a human, who
   overrides with a comment. Show the audit trail update.
5. **Off-brief** — a lifestyle/serum clip scores low relevance and is blocked at the gate before
   any policy spend. "We don't pay to deep-analyze content that isn't even the ad."
6. **Close with trust** — show the **eval harness**: 16/16, confusion matrix, per-policy P/R/F1.
   "This is how we ship a policy change to a live advertiser without holding our breath."

**Three sentences for the reviewer/interviewer:**
> The model perceives, a deterministic engine decides, and every verdict is backed by a timestamp
> you can watch. Policy is per-campaign configuration, validated offline by an eval harness, so a
> threshold change is a safe, testable deploy — not a gamble on a prompt. It's built for the Ads
> Compliance team that has to defend each call to the advertiser.

---

## 6. Artifacts in this repo

- **Live app** — three-pane reviewer console (queue · video + evidence · decision)
- **`backend/`** — FastAPI pipeline, `decision.py` engine, `policies.yaml`, TwelveLabs client
- **`backend/eval/`** — labeled dataset + `run_eval.py` (confusion matrix, P/R/F1), `make eval`
- **`docs/`** — design doc, screenshots, this submission doc
- **README** — setup + architecture
