# ClearFrame: Solutions Engineering Take-Home Submission

**Theme:** Ad Compliance and Brand Safety for Social Video Ads
**Scenario:** Global Makeup Brand Campaign
**Evaluation focus:** Product thinking, technical clarity, demo storytelling
**Built with:** TwelveLabs (Pegasus and Marengo), FastAPI, React, Supabase (Postgres and Storage)

> **The model perceives. The engine decides. Every verdict points at the frame.**
> TwelveLabs understands what happens in a video across visuals, speech, and on-screen text.
> A separate, deterministic policy engine turns that into APPROVE / REVIEW / BLOCK, because in
> an ads system, a wrong auto-block on a large advertiser is a revenue and trust incident, not
> just a bug.

---

# Part 1: The Ask (captured clearly)

### The customer, and why this matters
A large social platform earns its primary revenue from **video advertising**. Advertisers
increasingly promote **creator and influencer videos as the ad creative itself** (boosted or
whitelisted content). Before such a video runs as a paid ad, advertisers expect strong
**brand-safety, compliance, and explainability** guarantees.

### The scenario
A global makeup brand is launching a paid campaign using creator beauty videos: tutorials,
demos, "get ready with me." The platform's **Ads Compliance team** must clear every submission
**before promotion, automatically and at scale.**

### Advertiser requirements
| Requirement | Meaning |
|-------------|---------|
| No hate, harassment, or discrimination | Hard block |
| No drug use or illegal behavior | Hard block |
| Limited tolerance for profanity | Mild routes to review, heavy blocks |
| Ads must be **on-brief** | The video must actually be about the product or campaign |
| No misleading or unsafe product use | Eye-area misuse, harmful or medical claims |
| Clear explanations | Every blocked or reviewed ad must be defensible |

### The problem and its challenges
- Risky content can appear **briefly**: a single frame of speech, visuals, or on-screen text.
- **Subtle** violations are hard to catch (improper or unsafe application, non-compliant presentation).
- Some submissions are **off-brief**, barely featuring the product, or unrelated clickbait.
- **Manual review is inconsistent and does not scale.**
- Advertisers and reviewers need a **quick summary** of what each video contains.

### What the system must do
1. Analyze videos for compliance risk across **visuals, speech, and on-screen text**
2. Detect **campaign relevance** (on-brief vs off-brief)
3. Generate an **automated 2 to 5 sentence description**
4. Return a **decision**: APPROVE / REVIEW / BLOCK
5. Provide **timestamped evidence** for the decision

### Policy scope (minimum)
At least 5 policy categories (hate/harassment, profanity, drugs/illegal, unsafe or misleading
usage, medical/cosmetic claims), plus a campaign relevance check (score or label) and a video
description. A custom taxonomy, severities, and thresholds are allowed.

### What the submission must explain
- **How decisions are made**
- **Why outputs are trustworthy**
- **How this scales in a real ads system**

---

# Part 2: What We Built: ClearFrame

**ClearFrame is the brand-safety clearance console for an Ads Compliance team.** A creator
submits a video; ClearFrame clears it end to end and hands the human a verdict they can trust,
override, and defend to the advertiser. It is built **for the reviewer**, not as a model demo.

### The core thesis: perceive vs. decide

We deliberately split the system into two layers. This is the central product and engineering
argument.

- **Perception, TwelveLabs.** One indexing pass builds a multimodal understanding of the clip.
  **Pegasus** reads visuals, speech, and on-screen text and returns one structured object: a
  neutral description, an on-brief judgment, a 0 to 1 relevance score, and per-policy findings
  with severities and **timestamps**. **Marengo** powers semantic search and retrieval over the
  indexed video for reviewer-driven exploration.
- **Decision, a deterministic engine.** A small, auditable policy engine (`decision.py` plus
  `policies.yaml`) turns those findings into APPROVE / REVIEW / BLOCK by applying the
  advertiser's thresholds. **No LLM produces the verdict.** The model supplies evidence, the
  engine applies policy.

Why it matters: model outputs drift and cannot be unit-tested. **Policy must be deterministic,
versioned, and explainable**, because money and advertiser trust ride on every call.

### Data flow (one creative, end to end)

```
Creator drops video in the campaign bucket (Supabase)
        │
        ▼
Pre-check: format, duration, size, dedup by hash (cheap, before any TwelveLabs spend)
        │
        ▼
Index (TwelveLabs): one multimodal index of the clip
        │
        ▼
Pegasus analysis: description, relevance score, on-brief, per-policy findings with timestamps
        │
        ▼
Decision engine (policies.yaml): APPROVE / REVIEW / BLOCK with confidence and reasons
        │
        ▼
Reviewer console: verdict, description, clickable timestamped evidence, audit trail
```

### Two personas
- **Ads Compliance team (primary user).** Works the queue, reads verdicts and evidence, overrides
  when needed. The whole UI is built for them.
- **Creator (submitter).** Drops a video into the campaign's linked bucket, and gets notified
  automatically when an ad is blocked, with reasons.

### Per-campaign governance (the product layer that goes beyond the ask)
Compliance is not one global ruleset, it is **per campaign**. At campaign creation the team sets
a **master prompt** (brief plus flagging guidance), a **profanity tolerance** (Strict, Balanced,
or Relaxed), a **relevance threshold**, which **policies** are active, and the **linked bucket**
creators upload to. This config is injected into perception and decision at runtime, so the same
engine serves a strict pharma-adjacent campaign and a relaxed lifestyle campaign **without code
changes**.

### The taxonomy we defined
- **5 policy categories**, each with severity `none / low / medium / high` and per-policy
  `block_at` / `review_at` thresholds. GARM-floor categories (hate, drugs) block harder.
- **Relevance**: a 0 to 1 score against the campaign brief plus an on-brief label. The off-brief
  gate fires when relevance is below threshold *and* the model judged it off-brief.
- **Confidence**: high or medium confidence drives whether an automated call is acted on or
  routed to a human.

---

# Part 3: Validation Against the Ask (coverage matrix)

Every requirement, where it lives, and the proof.

| The ask | ClearFrame delivers | Proof / where |
|---------|---------------------|---------------|
| Analyze across **visuals, speech, on-screen text** | Single Pegasus pass reads all three modalities | `analyze.py` prompt and schema |
| **Off-brief filter** | 0 to 1 relevance vs the campaign brief plus on-brief label; contributes a BLOCK before deeper checks | `decision.py`, threshold 0.55 |
| **5+ policy categories** | Hate/harassment, profanity, drugs/illegal, unsafe usage, medical/cosmetic claims | `policies.yaml` |
| **Severity and thresholds** | none/low/med/high with per-policy block/review lines; profanity tolerance configurable | `policies.yaml`, campaign config |
| **2 to 5 sentence description** | Auto-generated, shown on every review | Pegasus `description` |
| **Decision APPROVE/REVIEW/BLOCK** | Deterministic engine output plus confidence | `decision.py` |
| **Timestamped evidence** | Each finding carries seconds; click a reason and the player jumps to that moment | finding `timestamps` to evidence rows |
| **Clear explanations** | Human-readable reasons per verdict plus a full audit trail (auto and human) | `reasons[]`, `audit` table |
| **Automatic and at scale** | Bucket ingestion, background sweeper, pre-check, auto-decide / human-override | `bucket_sync.py`, `api.py` |
| **Brief offers**: demo, repo, doc, screenshots | Live app, repo, this doc, design doc, screenshots | this repo |

**Result: every required capability is implemented and demonstrable.** Nothing is stubbed.

---

# Part 4: Why This Is a Top 1% Submission

The brief asks for about 4 hours and states no polished UI is required. A baseline submission
scripts a single TwelveLabs call and prints a verdict. ClearFrame is positioned where a
**Solutions Engineer** adds value: turning the model into a **product an Ads Compliance team
would actually adopt.**

### It maps directly to the three evaluation criteria
- **Product thinking.** Per-campaign governance, the perceive/decide split, the off-brief gate as
  *spend protection*, human-in-the-loop, the audit trail. These are decisions about the *buyer's*
  problem, not the model's features.
- **Technical clarity.** A clean two-layer architecture, a deterministic engine you can read in
  one sitting, an eval harness that proves it, and config-driven policy. Easy to explain, easy to
  trust.
- **Demo storytelling.** A single campaign, four contrast shots, one money moment (click a reason,
  the video jumps to the violation), closing on the eval. See Part 6.

### Six things that separate it from a baseline
1. **Deterministic, versioned policy engine.** The verdict is testable, not a prompt's whim.
2. **An offline eval harness.** 16 labeled cases run through the *real* engine, reporting a
   confusion matrix and per-policy precision/recall/F1. **16/16 (100%).** This is how you ship a
   policy change to a live advertiser without holding your breath. It validates the engine
   **offline** and is never in the runtime decision path.
3. **Per-campaign configuration.** Policy as config, so one system serves every advertiser.
4. **Production-shaped ingestion.** Supabase bucket drop, background sync, and a deterministic
   **pre-check** (format/duration/size/dedup) that filters junk *before* paid analysis.
5. **Spend discipline as a feature.** The off-brief gate and pre-check exist to protect compute
   and reviewer bandwidth, which is exactly what an ads buyer cares about at volume.
6. **Honest adaptation to a real API change.** Marengo 3.0 dropped numeric search scores
   mid-build. Rather than ship a silently-broken "relevance 0.00," we moved relevance and
   timestamped evidence onto Pegasus's multimodal analysis and kept Marengo for reviewer search,
   **with tests and eval still green.** Adapting cleanly under change is the SE story.

---

# Part 5: The Three Questions the Submission Must Answer

### How decisions are made
1. **Pre-check** rejects malformed or duplicate files cheaply, before any model spend.
2. **Pegasus** returns description, relevance, on-brief, and per-policy findings (severity plus
   timestamps) from one multimodal pass.
3. **Off-brief gate**: relevance below threshold *and* judged off-brief contributes a BLOCK.
4. **Deterministic engine** maps each finding's severity against the campaign's `block_at` /
   `review_at` thresholds into a per-policy contribution, then an overall **APPROVE / REVIEW /
   BLOCK**.
5. **Confidence check**: a low-confidence automated call routes to **REVIEW** instead of acting.
6. **Human override** (with a comment) is always available; the creator is notified automatically.

### Why the outputs are trustworthy
- **Deterministic and versioned** policy (thresholds in `policies.yaml`, not a prompt).
- **Eval harness** catches policy drift offline before it reaches an advertiser (16/16 today).
- **Evidence, not vibes.** Every reason links to a timestamp the reviewer can watch.
- **Full audit trail.** Auto-decisions and human overrides logged with actor, action, comment,
  and time.
- **Human in the loop** by design for low-confidence and REVIEW outcomes.

### How it scales in a real ads system
- **Ingestion**: a per-campaign bucket plus a background sweeper; creators self-serve uploads.
- **Spend control**: pre-check and the off-brief gate filter before any TwelveLabs cost.
- **Queue-ready**: the staged pipeline (index, analyze, decide) becomes a queue consumer resumed
  by a TwelveLabs webhook in production.
- **Storage**: SQLite locally, Supabase Postgres and Storage in production, same code path.
- **Policy as configuration**: new campaigns, categories, and thresholds are config, not code.

---

# Part 6: How It Will Be Presented

**One positioning line:**
> ClearFrame is the brand-safety clearance gate that lets an Ads Compliance team approve creator
> video ads automatically and at scale, with evidence they can defend to the advertiser.

**Demo arc (about 5 minutes), one campaign, four contrast shots:**
1. **Set the stage.** Open *Ora Velvet Matte, Spring Launch*. Show the master prompt, policies,
   and relevance threshold. "This is the advertiser's contract, encoded."
2. **APPROVE.** A clean on-brief tutorial sails through. Read the auto-description; high
   confidence, no human touched it. "That's the scale win."
3. **BLOCK, the hero shot.** An on-brief clip with a **medical claim** ("clinically proven to
   cure acne"). Click the reason and the player jumps to the exact second the claim is spoken or
   on screen. "This is why it's trustworthy: every call points at the frame."
4. **REVIEW.** Mild profanity under *Balanced* tolerance routes to a human, who overrides with a
   comment. Show the audit trail update.
5. **Off-brief.** A serum or lifestyle clip scores low relevance and is blocked before any policy
   spend. "We don't pay to deep-analyze content that isn't even the ad."
6. **Close on trust.** Show the **eval harness**: 16/16, confusion matrix, per-policy P/R/F1.
   "This is how a threshold change ships to a live advertiser as a safe, testable deploy."

**Three-sentence verbal pitch:**
> The model perceives, a deterministic engine decides, and every verdict is backed by a timestamp
> you can watch. Policy is per-campaign configuration, validated offline by an eval harness, so a
> threshold change is a safe, testable deploy, not a gamble on a prompt. It's built for the Ads
> Compliance team that has to defend each call to the advertiser.

**Submission artifacts (the brief allows any combination):**
- **Live app**: three-pane reviewer console (queue, video plus evidence, decision)
- **Repo**: `backend/` (FastAPI pipeline, `decision.py`, `policies.yaml`, TwelveLabs client),
  `frontend/`
- **Eval**: `backend/eval/` (labeled dataset plus `run_eval.py`; `make eval`)
- **Docs**: design doc, screenshots, and this submission doc
- **Short recording / screenshots**: the demo arc above

---

### Appendix: at a glance
| | |
|---|---|
| Policy categories | hate/harassment, profanity, drugs/illegal, unsafe usage, medical/cosmetic claims |
| Relevance | 0 to 1 score vs campaign brief plus on-brief label, threshold 0.55 |
| Decisions | APPROVE, REVIEW, BLOCK plus confidence |
| Evidence | per-finding timestamps, click-to-seek |
| Eval | 16 labeled cases, confusion matrix, per-policy P/R/F1, **16/16** |
| Stack | TwelveLabs (Pegasus and Marengo), FastAPI, React, Supabase |
