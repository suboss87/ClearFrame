import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  FileCheck, CheckCircle2, AlertTriangle, XCircle, Play, Pause, Clock,
  Eye, Mic, Type, ChevronRight, ChevronDown, Sparkles, UserCheck, Search,
  Loader2, Film, X, Check, MinusCircle, Layers, Plus, UploadCloud, Command,
  Inbox, Cloud, PanelLeftClose, PanelLeft, Settings, MessageSquare, Send,
  Key, EyeOff, ShieldCheck, Keyboard, Zap, Activity, Hash, ArrowUp, ArrowDown,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Clearframe — single-screen, three-pane reviewer console, built for scale.
//   left rail  : pinned "processing" section + searchable, foldered queue that
//                stays usable at 100+ creatives (collapse-by-default folders,
//                per-folder verdict bars, "needs attention" default, Unsorted
//                inbox, New Campaign + Drive-sync entry points).
//   center     : evidence timeline for a decided creative, or the live stepper
//                for one still being processed.
//   right      : the decision (verdict, reasons, policy checks, human override).
// Demo mode runs the whole thing without a backend; set API_BASE for live.
// ---------------------------------------------------------------------------
// Where the backend lives. The app pings /api/health on load: if it answers,
// the UI runs LIVE (real campaigns, real pipeline, real chat); if not, it falls
// back to the self-contained demo so it always renders.
const API_BASE = (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_API_BASE) || "http://localhost:8000";

// --- Live API helpers ------------------------------------------------------
async function apiUpload(files, campaignId) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  if (campaignId) fd.append("campaign_id", campaignId);
  const res = await fetch(`${API_BASE}/api/reviews/upload`, { method: "POST", body: fd });
  return (await res.json()).reviews;
}
async function apiPoll(id, onStage) {
  let last = -1;
  for (let i = 0; i < 120; i++) {
    const r = await (await fetch(`${API_BASE}/api/reviews/${id}`)).json();
    if (typeof r.stage === "number" && r.stage !== last) { last = r.stage; onStage?.(r.stage); }
    if (r.status === "done" || r.status === "failed") return r.result;
    await new Promise((res) => setTimeout(res, 500));
  }
  return null;
}
function hashHue(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function adaptResult(r, file) {
  const policies = (r.policy_verdicts || []).map((p) => ({
    id: p.policy_id, label: p.label, status: p.triggered ? "flagged" : "clean",
    severity: p.severity, contribution: p.contribution,
    evidence: (p.evidence || []).map((e) => ({ start: e.start, end: e.end, confidence: e.confidence, modality: "visual", label: e.query })),
  }));
  return {
    id: newId(), file, campaignId: r.campaign_id,
    creator: "@" + file.replace(/\.[^.]+$/, "").replace(/[_-]/g, "."),
    duration: 75, hue: hashHue(file), verdict: r.decision, confidence: r.confidence,
    relevance: r.relevance_score ?? 0, onBrief: r.on_brief, humanReview: r.human_review_required,
    description: r.description, reasons: r.reasons || [], policies,
    offBriefGate: r.on_brief === false && policies.length === 0,
  };
}
// Map a backend review row -> the shapes the UI already renders, preserving the
// backend's own id so polling, chat and decisions reference the same record.
function adaptBackendReview(r) {
  const v = adaptResult(r.result || {}, r.file || "creative.mp4");
  v.id = r.id; v.campaignId = r.campaign_id; v.humanDecision = r.human_decision || null;
  return v;
}
function adaptBackendJob(r) {
  return { id: r.id, file: r.file, campaignId: r.campaign_id, stage: typeof r.stage === "number" ? r.stage : 0, done: false, error: r.status === "failed" };
}
const jget = (p) => fetch(`${API_BASE}${p}`).then((r) => r.json());
const jpost = async (p, body) => {
  const r = await fetch(`${API_BASE}${p}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
};

// --- Static config ---------------------------------------------------------
const VERDICT = {
  APPROVE: { color: "#34d399", soft: "rgba(52,211,153,0.12)", label: "Approve", Icon: CheckCircle2 },
  REVIEW:  { color: "#fbbf24", soft: "rgba(251,191,36,0.12)", label: "Review",  Icon: AlertTriangle },
  BLOCK:   { color: "#fb7185", soft: "rgba(251,113,133,0.12)", label: "Block",   Icon: XCircle },
};
const MODALITY_ICON = { visual: Eye, audio: Mic, text: Type };

const PIPELINE = [
  { key: "INDEXING",  label: "Indexing",          detail: "Building a searchable index of frames, speech and on-screen text", Icon: Film },
  { key: "RELEVANCE", label: "Relevance gate",    detail: "Checking the creative is on-brief for this campaign",              Icon: Search },
  { key: "ANALYZING", label: "Analyzing",         detail: "Reasoning over the video for policy violations",                   Icon: Sparkles },
  { key: "EVIDENCE",  label: "Gathering evidence", detail: "Finding timestamped clips that corroborate each policy",          Icon: Eye },
  { key: "DECIDING",  label: "Deciding",          detail: "Combining the signals into a deterministic verdict",              Icon: FileCheck },
];
const DONE_STAGE = PIPELINE.length;
const GATED_SKIP = [2, 3];
const STAGE_MS = [1100, 700, 950, 800, 600];
const CAP = 14; // max creatives rendered per open folder before "+N more"

const TEMPLATES = {
  clean_tutorial: {
    creator: "@maya.beauty", duration: 75, verdict: "APPROVE", confidence: "high", relevance: 0.88, onBrief: true, humanReview: false, hue: 168,
    description: "A creator demonstrates a matte lipstick and foundation from the Lumiere Velvet Matte collection, applying each evenly to the face while narrating the steps. The focus stays on the product throughout.",
    reasons: ["No policy violations detected. On-brief and clean across all categories."],
    policies: [
      { id: "hate", label: "Hate / harassment", status: "clean" }, { id: "drugs", label: "Drugs / illegal behaviour", status: "clean" },
      { id: "profanity", label: "Profanity", status: "clean" }, { id: "unsafe", label: "Unsafe product usage", status: "clean" },
      { id: "claims", label: "Medical / cosmetic claims", status: "clean" },
    ],
  },
  eye_misuse_claim: {
    creator: "@priya.glow", duration: 78, verdict: "BLOCK", confidence: "high", relevance: 0.82, onBrief: true, humanReview: false, hue: 350,
    description: "A creator demonstrates an eyeliner and serum, applying product onto the inner waterline in a way that touches the eyeball, then stating the serum cures acne and treats rosacea within a week.",
    reasons: ["Unsafe product usage at high severity, corroborated by a timestamped clip.", "Medical claim at high severity: a cosmetic cannot claim to cure acne or treat rosacea."],
    policies: [
      { id: "hate", label: "Hate / harassment", status: "clean" }, { id: "drugs", label: "Drugs / illegal behaviour", status: "clean" }, { id: "profanity", label: "Profanity", status: "clean" },
      { id: "unsafe", label: "Unsafe product usage", status: "flagged", severity: "high", contribution: "BLOCK", evidence: [{ start: 34, end: 42, confidence: "high", modality: "visual", label: "Product applied onto the eyeball and inner waterline" }] },
      { id: "claims", label: "Medical / cosmetic claims", status: "flagged", severity: "high", contribution: "BLOCK", evidence: [{ start: 57, end: 61, confidence: "high", modality: "audio", label: "Claims the serum cures acne and treats rosacea" }] },
    ],
  },
  mild_profanity: {
    creator: "@jordan.grwm", duration: 70, verdict: "REVIEW", confidence: "high", relevance: 0.86, onBrief: true, humanReview: true, hue: 41,
    description: "A get ready with me routine using the matte foundation and lipstick, shown clearly on the face. At one point the creator uses a single mild swear word reacting to a smudge, then continues normally.",
    reasons: ["Profanity at low severity: below the block threshold, above the review threshold.", "Limited profanity tolerance for this advertiser routes a single instance to a human."],
    policies: [
      { id: "hate", label: "Hate / harassment", status: "clean" }, { id: "drugs", label: "Drugs / illegal behaviour", status: "clean" },
      { id: "profanity", label: "Profanity", status: "flagged", severity: "low", contribution: "REVIEW", evidence: [{ start: 46.5, end: 48, confidence: "medium", modality: "audio", label: "A single mild swear word reacting to a smudge" }] },
      { id: "unsafe", label: "Unsafe product usage", status: "clean" }, { id: "claims", label: "Medical / cosmetic claims", status: "clean" },
    ],
  },
  offbrief_clickbait: {
    creator: "@dailyvibes", duration: 64, verdict: "BLOCK", confidence: "high", relevance: 0.28, onBrief: false, humanReview: false, hue: 280, offBriefGate: true,
    description: "A fast-paced lifestyle vlog of errands, coffee and a short dance. A makeup product appears briefly on a table but is never picked up, named or applied. Most of the runtime is unrelated to cosmetics.",
    reasons: ["Off-brief: relevance 0.28 is below the 0.55 threshold and the model judged it off-brief.", "Rejected at the relevance gate before deep compliance analysis ran."],
    policies: [
      { id: "hate", label: "Hate / harassment", status: "skipped" }, { id: "drugs", label: "Drugs / illegal behaviour", status: "skipped" }, { id: "profanity", label: "Profanity", status: "skipped" },
      { id: "unsafe", label: "Unsafe product usage", status: "skipped" }, { id: "claims", label: "Medical / cosmetic claims", status: "skipped" },
    ],
  },
};
const TEMPLATE_KEYS = Object.keys(TEMPLATES);

const fmt = (s) => `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, "0")}`;
let seq = 100; const newId = () => `rv_${++seq}`;
let cmpSeq = 1; const newCampaignId = () => `cmp_${++cmpSeq}`;

function makeReview(file, templateKey, campaignId) { return { id: newId(), file, campaignId, ...TEMPLATES[templateKey], _key: templateKey }; }
function pickTemplate(filename) {
  const f = filename.toLowerCase();
  return TEMPLATE_KEYS.find((k) => f.includes(k.split("_")[0])) || TEMPLATE_KEYS[Math.floor((f.length * 7) % TEMPLATE_KEYS.length)];
}

// --- Seed data at scale ----------------------------------------------------
const SEED_CAMPAIGNS = [
  { id: "cmp_summer",  name: "Summer Glow 2026",     brief: "SPF + bronzer creator hauls and tutorials for the summer line.", createdAt: "2 days ago" },
  { id: "cmp_holiday", name: "Holiday Edit",          brief: "Festive gift-set reveals and glam looks for Q4.",                createdAt: "1 week ago" },
  { id: "cmp_seed",    name: "Lumiere Velvet Matte",  brief: "Spring 2026 launch — matte lipstick & foundation tutorials.",    createdAt: "Spring 2026" },
];
const UNSORTED = { id: "cmp_unsorted", name: "Unsorted", brief: "Single, ad-hoc creatives not tied to a campaign.", isInbox: true };
const HANDLES = ["ava.lux", "noah.glow", "mia.beauty", "liam.rae", "zoe.k", "kai.m", "ivy.rose", "leo.b", "nina.h", "omar.s", "ruby.t", "eli.j", "sana.p", "theo.w", "uma.d", "wes.c", "yara.f", "zane.q", "cleo.v", "milo.x"];
const MIX = ["clean_tutorial", "clean_tutorial", "clean_tutorial", "mild_profanity", "clean_tutorial", "eye_misuse_claim", "clean_tutorial", "clean_tutorial", "offbrief_clickbait", "mild_profanity"];
function genReviews(campaignId, n, seed = 0) {
  return Array.from({ length: n }, (_, i) => {
    const key = MIX[(i + seed) % MIX.length];
    const rv = makeReview(`${key.split("_")[0]}_${(i + 1).toString().padStart(2, "0")}.mp4`, key, campaignId);
    rv.creator = "@" + HANDLES[(i + seed) % HANDLES.length];
    rv.hue = (i * 53 + seed * 17) % 360;
    return rv;
  });
}
function seedReviews() {
  return [
    ...genReviews("cmp_summer", 52, 0),
    ...genReviews("cmp_holiday", 23, 3),
    ...["clean_tutorial", "eye_misuse_claim", "mild_profanity", "offbrief_clickbait"].map((k) => makeReview(`${k}.mp4`, k, "cmp_seed")),
    ...genReviews("cmp_unsorted", 5, 7),
  ];
}
const RANK = { BLOCK: 0, REVIEW: 1, APPROVE: 2 };
const DRIVE_FILES = ["drive_grwm_01.mp4", "drive_tutorial_02.mp4", "drive_review_03.mp4", "drive_lookbook_04.mp4", "drive_haul_05.mp4", "drive_demo_06.mp4"];

// ===========================================================================
export default function ClearframeApp() {
  const [campaigns, setCampaigns] = useState([...SEED_CAMPAIGNS, UNSORTED]);
  const [reviews, setReviews] = useState(seedReviews);
  const [jobs, setJobs] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("ALL"); // ALL | BLOCK | REVIEW | APPROVE
  const [collapsed, setCollapsed] = useState({ cmp_summer: false }); // first folder open
  const [showAll, setShowAll] = useState({}); // per-folder "+N more" expansion
  const [showUpload, setShowUpload] = useState(false);
  const [uploadNew, setUploadNew] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [topH, setTopH] = useState(null); // center top-region height (null = fit content; chat fills the rest)
  const topRef = useRef(null);
  const [decisions, setDecisions] = useState({}); // { reviewId: "APPROVE" | "BLOCK" } human calls
  const [toast, setToast] = useState(null);
  const [live, setLive] = useState(false); // backend reachable -> real data + pipeline
  const searchRef = useRef(null);
  const quickRef = useRef(null); // hidden input for single quick uploads

  const showToast = (m) => { setToast(m); setTimeout(() => setToast(null), 2600); };
  const cmpName = (id) => campaigns.find((c) => c.id === id)?.name || "—";
  const selected = useMemo(() => reviews.find((r) => r.id === selectedId) || jobs.find((j) => j.id === selectedId) || null, [reviews, jobs, selectedId]);
  const selectedIsJob = !!jobs.find((j) => j.id === selectedId);
  const isCol = (id) => collapsed[id] ?? true; // collapsed unless explicitly opened
  const decide = (id, action) => {
    const r = reviews.find((x) => x.id === id); if (!r) return;
    setDecisions((d) => ({ ...d, [id]: action }));
    showToast(action === "APPROVE" ? `Approved · ${r.creator}` : `Blocked · ${r.creator}`);
    if (live) jpost(`/api/reviews/${id}/decision`, { decision: action }).catch(() => {});
  };
  const undoDecide = (id) => setDecisions((d) => { const n = { ...d }; delete n[id]; return n; });

  // ---- live data sync (active only when the backend is reachable) ----------
  const loadCampaigns = useCallback(async () => {
    const cs = await jget("/api/campaigns");
    const mapped = cs.map((c) => ({ id: c.id, name: c.name, brief: c.brief, isInbox: c.id === "cmp_unsorted" }));
    setCampaigns(mapped);
    const firstReal = mapped.find((c) => !c.isInbox) || mapped[0];
    if (firstReal) setCollapsed((m) => ({ ...m, [firstReal.id]: false }));
  }, []);
  const loadReviews = useCallback(async () => {
    const rs = await jget("/api/reviews");
    setReviews(rs.filter((r) => r.status === "done" && r.result).map(adaptBackendReview));
    setJobs(rs.filter((r) => r.status === "queued" || r.status === "processing").map(adaptBackendJob));
    const dec = {}; rs.forEach((r) => { if (r.human_decision) dec[r.id] = r.human_decision; });
    setDecisions((d) => ({ ...d, ...dec }));
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const h = await jget("/api/health");
        if (h && h.ok) { setLive(true); setCollapsed({}); await loadCampaigns(); await loadReviews(); }
      } catch { /* no backend -> stay in demo mode */ }
    })();
  }, [loadCampaigns, loadReviews]);

  // While anything is processing, refetch so stages advance and verdicts land.
  useEffect(() => {
    if (!live || !jobs.length) return;
    const t = setInterval(loadReviews, 1500);
    return () => clearInterval(t);
  }, [live, jobs.length, loadReviews]);

  // ---- intake (demo + live) ------------------------------------------------
  const runStages = useCallback((job, startDelay, campaignId) => {
    const skip = job.gated ? GATED_SKIP : [];
    const order = []; for (let s = 0; s < DONE_STAGE; s++) if (!skip.includes(s)) order.push(s);
    let t = startDelay + 300;
    order.forEach((s) => { setTimeout(() => setJobs((x) => x.map((j) => (j.id === job.id ? { ...j, stage: s } : j))), t); t += STAGE_MS[s] || 700; });
    setTimeout(() => {
      const rv = makeReview(job.file, job.key, campaignId);
      setReviews((r) => [rv, ...r]);
      setJobs((x) => x.filter((j) => j.id !== job.id));
      setSelectedId((p) => (p === job.id ? rv.id : p));
    }, t);
  }, []);

  const intake = useCallback(async (fileList, campaignId) => {
    const files = Array.from(fileList); if (!files.length) return;
    if (live) {
      if (!(files[0] instanceof File)) { showToast("Drive sync is simulated; wire it in the backend (Phase 2) to ingest for real."); return; }
      setCollapsed((c) => ({ ...c, [campaignId]: false }));
      try {
        const submitted = await apiUpload(files, campaignId);
        if (submitted && submitted[0]) setSelectedId(submitted[0].id);
        await loadReviews();
      } catch { showToast("Upload failed — is the backend running?"); }
      return;
    }
    // demo: simulate the pipeline locally
    const fresh = files.map((f) => { const key = pickTemplate(f.name); return { id: newId(), file: f.name, campaignId, key, stage: 0, gated: !!TEMPLATES[key].offBriefGate, done: false }; });
    setJobs((x) => [...fresh, ...x]);
    setCollapsed((c) => ({ ...c, [campaignId]: false }));
    setSelectedId(fresh[0].id);
    fresh.forEach((job, i) => runStages(job, i * 300, campaignId));
  }, [runStages, live, loadReviews]);

  // Ingest a video by URL (Google Drive share link or any public video URL).
  const intakeUrl = async (url, campaignId) => {
    if (!live) { showToast("Connect the backend + a TwelveLabs key to ingest from a link."); return; }
    setCollapsed((c) => ({ ...c, [campaignId]: false }));
    try {
      const r = await jpost("/api/reviews/from-url", { url, campaign_id: campaignId });
      if (r && r.id) setSelectedId(r.id);
      await loadReviews();
      showToast("Fetching from Google Drive…");
    } catch (e) { showToast(String(e.message || e).slice(0, 160)); }
  };

  const createCampaign = async (name, brief) => {
    if (live) {
      const c = await jpost("/api/campaigns", { name: name.trim(), brief: brief.trim() });
      await loadCampaigns();
      setCollapsed((m) => ({ ...m, [c.id]: false }));
      return { id: c.id, name: c.name, brief: c.brief };
    }
    const c = { id: newCampaignId(), name: name.trim(), brief: brief.trim(), createdAt: "just now" };
    setCampaigns((cs) => [c, ...cs.filter((x) => !x.isInbox), UNSORTED]); // keep Unsorted last
    setCollapsed((m) => ({ ...m, [c.id]: false }));
    return c;
  };

  // ---- rail data -----------------------------------------------------------
  const q = query.trim().toLowerCase();
  const reviewVisible = (r) => {
    if (filter === "NEEDS") { if (r.verdict !== "BLOCK" && r.verdict !== "REVIEW") return false; }
    else if (filter !== "ALL") { if (r.verdict !== filter) return false; }
    if (!q) return true;
    const hay = [r.creator, r.file, cmpName(r.campaignId), ...(r.reasons || []), ...((r.policies || []).map((p) => p.label))].join(" ").toLowerCase();
    return hay.includes(q);
  };
  const jobItems = useMemo(() => jobs.map((j) => ({ ...j, _job: true })), [jobs]);
  const needsCount = useMemo(() => reviews.filter((r) => r.verdict === "BLOCK" || r.verdict === "REVIEW").length, [reviews]);

  const railModel = useMemo(() => {
    if (q) {
      const flatR = reviews.filter(reviewVisible).sort((a, b) => RANK[a.verdict] - RANK[b.verdict]);
      return { searching: true, results: flatR, flat: [...jobItems, ...flatR] };
    }
    const groups = campaigns.map((c) => {
      const all = reviews.filter((r) => r.campaignId === c.id);
      const items = all.filter(reviewVisible).sort((a, b) => RANK[a.verdict] - RANK[b.verdict]);
      return { campaign: c, all, items };
    }).filter((g) => g.items.length);
    const flat = [...jobItems];
    groups.forEach((g) => { if (!isCol(g.campaign.id)) (showAll[g.campaign.id] ? g.items : g.items.slice(0, CAP)).forEach((i) => flat.push(i)); });
    return { searching: false, groups, flat };
  }, [reviews, campaigns, jobItems, q, filter, collapsed, showAll]);

  const counts = useMemo(() => reviews.reduce((a, r) => { a[r.verdict] = (a[r.verdict] || 0) + 1; return a; }, { APPROVE: 0, REVIEW: 0, BLOCK: 0 }), [reviews]);

  // Ensure something is selected when nothing is. A selection stays valid by id
  // even if its folder is collapsed (so collapsing never clears the center) — we
  // only auto-pick when the selection is genuinely empty, never forcing a folder open.
  useEffect(() => {
    if (!selected && railModel.flat.length) setSelectedId(railModel.flat[0].id);
  }, [selected, railModel.flat]);

  // ---- keyboard ------------------------------------------------------------
  const flatRef = useRef(railModel.flat); flatRef.current = railModel.flat;
  const selRef = useRef(selectedId); selRef.current = selectedId;
  useEffect(() => {
    const onKey = (e) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
      if (e.key === "Escape") { if (showUpload) setShowUpload(false); if (showSettings) setShowSettings(false); if (showShortcuts) setShowShortcuts(false); document.activeElement?.blur?.(); return; }
      if (e.key === "?") { e.preventDefault(); setShowShortcuts((s) => !s); return; }
      if (typing) return;
      if (e.key === "/") { e.preventDefault(); searchRef.current?.focus(); return; }
      if (e.key === "u" || e.key === "n") { e.preventDefault(); setUploadNew(e.key === "n"); setShowUpload(true); return; }
      const flat = flatRef.current; const idx = flat.findIndex((i) => i.id === selRef.current);
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); if (flat.length) setSelectedId(flat[Math.min(flat.length - 1, idx + 1)]?.id ?? flat[0].id); }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); if (flat.length) setSelectedId(flat[Math.max(0, idx - 1)]?.id ?? flat[0].id); }
      else if (e.key === "a") { decide(selRef.current, "APPROVE"); }
      else if (e.key === "b") { decide(selRef.current, "BLOCK"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showUpload, showSettings, reviews]);

  const openUpload = (asNew) => { setUploadNew(asNew); setShowUpload(true); };
  const FILTERS = [
    { k: "ALL",     label: "All",     badge: reviews.length },
    { k: "BLOCK",   label: "Block",   badge: counts.BLOCK },
    { k: "REVIEW",  label: "Review",  badge: counts.REVIEW },
    { k: "APPROVE", label: "Approve", badge: counts.APPROVE },
  ];

  return (
    <div style={{ background: "#020617", color: "#e2e8f0", height: "100vh", display: "flex", flexDirection: "column", fontFamily: "'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif" }}>
      {/* Brand stripe */}
      <div style={{ height: 2, background: "linear-gradient(90deg,#34d399 0%,#22d3ee 50%,#6366f1 100%)", flexShrink: 0 }} />

      {/* Header */}
      <header className="flex items-center justify-between px-5" style={{ height: 54, borderBottom: "1px solid #1e293b", flexShrink: 0 }}>
        <div className="flex items-center gap-3">
          <Logo size={32} />
          <div>
            <div className="font-semibold" style={{ fontSize: 15, letterSpacing: "-0.02em" }}>Clear<span style={{ color: "#34d399" }}>Frame</span></div>
          </div>

          {/* divider */}
          <div style={{ width: 1, height: 22, background: "#1e293b", margin: "0 4px" }} />

          {/* Workspace + mode badge */}
          <div className="flex items-center gap-2">
            <span style={{ fontSize: 12.5, fontWeight: 500, color: "#94a3b8" }}>Lumiere Cosmetics</span>
            <span className="flex items-center gap-1" style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.04em", color: "#34d399", background: "rgba(52,211,153,0.1)", border: "1px solid rgba(52,211,153,0.3)", borderRadius: 99, padding: "2px 7px" }}>
              <span className="cf-live-dot" style={{ width: 5, height: 5, borderRadius: 99, background: "#34d399", display: "inline-block" }} />
              LIVE
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Keyboard hint */}
          <button onClick={() => setShowShortcuts(true)} title="Keyboard shortcuts (?)" className="flex items-center justify-center rounded-md" style={{ width: 30, height: 30, background: "transparent", border: "1px solid #1e293b", color: "#64748b" }}>
            <Keyboard size={14} />
          </button>

          <input ref={quickRef} type="file" accept="video/*" style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) intake([f], "cmp_unsorted"); e.target.value = ""; }} />
          <button onClick={() => quickRef.current?.click()} title="Quick upload — one video, straight to Unsorted" className="cf-upload-btn flex items-center gap-1.5 rounded-lg" style={{ background: "linear-gradient(135deg,#34d399,#22d3ee)", color: "#020617", fontSize: 12.5, fontWeight: 700, padding: "6px 14px", border: "none" }}>
            <UploadCloud size={14} color="#020617" /> Upload
          </button>
        </div>
      </header>

      <div className="flex" style={{ flex: 1, minHeight: 0 }}>
        {/* ── Activity bar (Replit-style thin strip, always visible) ── */}
        <div className="flex flex-col items-center" style={{ width: 40, background: "#080f1e", borderRight: "1px solid #14203a", flexShrink: 0 }}>
          <div style={{ flex: 1 }} />
          <button
            onClick={() => setRailOpen((v) => !v)}
            title={railOpen ? "Collapse queue (b)" : "Expand queue"}
            style={{ width: 32, height: 32, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 8, color: railOpen ? "#94a3b8" : "#34d399", background: railOpen ? "transparent" : "rgba(52,211,153,0.08)", border: "none", marginBottom: 10, transition: "all 0.15s ease" }}>
            {railOpen ? <PanelLeftClose size={17} /> : <PanelLeft size={17} />}
          </button>
        </div>

        {/* ----------------------------------------------------------- Rail */}
        <aside className="flex flex-col" style={{ width: railOpen ? 300 : 0, borderRight: railOpen ? "1px solid #1e293b" : "none", background: "#0b1220", flexShrink: 0, overflow: "hidden", transition: "width 0.2s ease" }}>
          {/* search */}
          <div style={{ padding: "12px 12px 8px", minWidth: 300 }}>
            <div className="flex items-center gap-2">
              <div className="cf-input-wrap flex items-center gap-2 rounded-lg" style={{ flex: 1, minWidth: 0, background: "#0e1729", border: "1px solid #1e293b", padding: "7px 10px" }}>
                <Search size={14} color="#64748b" />
                <input ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search creator, file, reason…"
                  style={{ background: "transparent", border: "none", outline: "none", color: "#e2e8f0", fontSize: 12.5, flex: 1, minWidth: 0 }} />
                {query ? <button onClick={() => setQuery("")}><X size={13} color="#64748b" /></button> : <kbd style={{ fontSize: 10, color: "#475569", border: "1px solid #1e293b", borderRadius: 4, padding: "1px 5px" }}>/</kbd>}
              </div>
            </div>
            <div className="flex items-center cf-scroll" style={{ marginTop: 8, gap: 4, overflowX: "auto", paddingBottom: 2 }}>
              {FILTERS.map((f) => {
                const on = filter === f.k;
                const tabColor = f.k === "NEEDS" ? "#fbbf24" : f.k === "BLOCK" ? "#fb7185" : f.k === "REVIEW" ? "#fbbf24" : f.k === "APPROVE" ? "#34d399" : "#e2e8f0";
                const tabBg = on ? (f.k === "NEEDS" ? "rgba(251,191,36,0.12)" : f.k === "BLOCK" ? "rgba(251,113,133,0.12)" : f.k === "REVIEW" ? "rgba(251,191,36,0.12)" : f.k === "APPROVE" ? "rgba(52,211,153,0.12)" : "#1e293b") : "transparent";
                const tabBorder = on ? (f.k === "NEEDS" ? "rgba(251,191,36,0.35)" : f.k === "BLOCK" ? "rgba(251,113,133,0.35)" : f.k === "REVIEW" ? "rgba(251,191,36,0.35)" : f.k === "APPROVE" ? "rgba(52,211,153,0.35)" : "#334155") : "#1e293b";
                return (
                  <button key={f.k} onClick={() => setFilter(f.k)} title={f.k === "NEEDS" ? `${f.badge} need attention (Block + Review)` : undefined}
                    className="cf-filter-tab flex items-center rounded-md" style={{ fontSize: 10.5, fontWeight: on ? 600 : 500, padding: "3px 7px", gap: 2.5, whiteSpace: "nowrap", background: tabBg, color: on ? tabColor : "#64748b", border: `1px solid ${tabBorder}` }}>
                    {f.k === "NEEDS" && f.badge > 0 && <AlertTriangle size={10} color={on ? "#fbbf24" : "#64748b"} />}
                    <span>{f.label}</span>
                    <span style={{ opacity: 0.65, fontSize: 10, fontWeight: 500 }}>{f.badge}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* list */}
          <div className="overflow-y-auto cf-scroll" style={{ flex: 1, minWidth: 300 }}>
            {/* pinned processing section */}
            {jobItems.length > 0 && (
              <div style={{ borderBottom: "1px solid #14203a", paddingBottom: 4 }}>
                <div className="flex items-center gap-1.5" style={{ padding: "8px 14px 4px", fontSize: 10.5, color: "#22d3ee", textTransform: "uppercase", letterSpacing: "0.06em" }}><Loader2 size={11} className="animate-spin" /> Processing {jobItems.length}</div>
                {jobItems.map((i) => <RailRow key={i.id} item={i} active={i.id === selectedId} onClick={() => setSelectedId(i.id)} />)}
              </div>
            )}

            {railModel.searching ? (
              <>
                <div style={{ padding: "8px 14px 4px", fontSize: 10.5, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em" }}>{railModel.results.length} result{railModel.results.length === 1 ? "" : "s"}</div>
                {railModel.results.map((i) => <RailRow key={i.id} item={i} active={i.id === selectedId} onClick={() => setSelectedId(i.id)} showCampaign cmpName={cmpName} />)}
                {!railModel.results.length && <Empty text="No creatives match." />}
              </>
            ) : (
              railModel.groups.map((g) => (
                <FolderGroup key={g.campaign.id} g={g} collapsed={isCol(g.campaign.id)} showAll={!!showAll[g.campaign.id]}
                  onToggle={() => setCollapsed((c) => ({ ...c, [g.campaign.id]: !isCol(g.campaign.id) }))}
                  onShowAll={() => setShowAll((s) => ({ ...s, [g.campaign.id]: true }))}
                  selectedId={selectedId} onSelect={setSelectedId} />
              ))
            )}
            {!railModel.searching && !railModel.groups.length && jobItems.length === 0 && (
              filter === "NEEDS" ? (
                <div className="flex flex-col items-center" style={{ padding: "32px 16px", textAlign: "center" }}>
                  <div style={{ fontSize: 26, marginBottom: 8 }}>🎉</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#64748b" }}>All clear</div>
                  <div style={{ fontSize: 11.5, color: "#334155", marginTop: 4, lineHeight: 1.5 }}>Nothing needs attention right now. Upload a new batch or switch to <span style={{ color: "#94a3b8" }}>All</span> to browse.</div>
                </div>
              ) : (
                <div className="flex flex-col items-center" style={{ padding: "32px 16px", textAlign: "center" }}>
                  <div className="cf-empty-icon flex items-center justify-center rounded-xl" style={{ width: 40, height: 40, background: "rgba(100,116,139,0.08)", border: "1px solid #1e293b", marginBottom: 10 }}>
                    <Film size={18} color="#334155" />
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#64748b" }}>No creatives yet</div>
                  <div style={{ fontSize: 11.5, color: "#334155", marginTop: 3, lineHeight: 1.5 }}>Upload a batch to start reviewing.</div>
                </div>
              )
            )}
          </div>

          {/* New Campaign + user + keyboard hint */}
          <div style={{ borderTop: "1px solid #14203a", minWidth: 300 }}>
            <button onClick={() => openUpload(true)} className="cf-new-campaign flex items-center justify-center gap-1.5" style={{ margin: "10px 0 8px 12px", padding: "9px 0", width: "calc(100% - 24px)", borderRadius: 8, border: "1px solid rgba(52,211,153,0.4)", color: "#34d399", fontSize: 12.5, fontWeight: 600 }}><Plus size={14} /> New Campaign</button>
            <button onClick={() => setShowSettings(true)} className="w-full flex items-center gap-2.5" style={{ padding: "8px 12px", borderTop: "1px solid #14203a", background: "transparent" }}>
              <div className="flex items-center justify-center rounded-full" style={{ width: 30, height: 30, flexShrink: 0, background: "linear-gradient(135deg,#6366f1,#22d3ee)", color: "#020617", fontSize: 11.5, fontWeight: 700 }}>SN</div>
              <div style={{ minWidth: 0, flex: 1, textAlign: "left" }}>
                <div className="truncate" style={{ fontSize: 12.5, fontWeight: 600 }}>Subash Natarajan</div>
                <div className="truncate" style={{ fontSize: 10.5, color: "#64748b" }}>Workspace &amp; settings</div>
              </div>
              <Settings size={15} color="#64748b" style={{ flexShrink: 0 }} />
            </button>
          </div>
        </aside>

        {/* --------------------------------------------------------- Center */}
        <main className="flex flex-col" style={{ flex: 1, minWidth: 0, overflow: "hidden" }}>
          <div ref={topRef} className="cf-scroll" style={{
            overflowY: "auto", padding: 22, minHeight: 0,
            ...(selected && !selectedIsJob
              ? (topH == null ? { flexGrow: 0, flexShrink: 1, flexBasis: "auto" } : { flexGrow: 0, flexShrink: 0, flexBasis: topH })
              : { flex: 1 }),
          }}>
            {!selected && <CenterEmpty onUpload={() => openUpload(false)} />}
            {selected && selectedIsJob && <JobInspector job={selected} cmpName={cmpName} />}
            {selected && !selectedIsJob && <VideoInspector v={selected} cmpName={cmpName} />}
          </div>
          {selected && !selectedIsJob && <ChatDock key={selected.id} v={selected} topRef={topRef} setTopH={setTopH} live={live} />}
        </main>

        {/* ---------------------------------------------------------- Right */}
        <aside className="overflow-y-auto cf-scroll" style={{ width: 360, borderLeft: "1px solid #1e293b", background: "#0b1220", flexShrink: 0 }}>
          {selected && selectedIsJob && <JobDecision job={selected} />}
          {selected && !selectedIsJob && <DecisionPanel v={selected} decided={decisions[selected.id]} onDecide={decide} onUndo={undoDecide} />}
          {!selected && (
            <div className="flex flex-col items-center justify-center" style={{ height: "100%", padding: 24 }}>
              <div style={{ position: "relative", width: 48, height: 48, marginBottom: 16 }}>
                <div style={{ width: 48, height: 48, borderRadius: 14, background: "rgba(52,211,153,0.07)", border: "1px solid rgba(52,211,153,0.14)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <FileCheck size={22} color="rgba(52,211,153,0.55)" />
                </div>
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#94a3b8", textAlign: "center", letterSpacing: "-0.01em" }}>Select a creative</div>
              <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 5, textAlign: "center", lineHeight: 1.6, maxWidth: 200 }}>Pick one from the queue to see its verdict, policy checks, and evidence.</div>
            </div>
          )}
        </aside>
      </div>

      {showUpload && <UploadModal campaigns={campaigns} reviews={reviews} initialNew={uploadNew} onClose={() => setShowUpload(false)} createCampaign={createCampaign} onIntake={intake} onIntakeUrl={intakeUrl} showToast={showToast} />}
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} showToast={showToast} live={live} />}
      {showShortcuts && <ShortcutsModal onClose={() => setShowShortcuts(false)} />}
      {toast && <div className="cf-toast fixed left-1/2" style={{ bottom: 24, transform: "translateX(-50%)", background: "#0f1e35", color: "#e2e8f0", fontSize: 13, fontWeight: 500, padding: "10px 18px", borderRadius: 10, boxShadow: "0 8px 32px rgba(0,0,0,0.6)", border: "1px solid #1e3a5f", borderTop: "2px solid #34d399", whiteSpace: "nowrap" }}>{toast}</div>}
    </div>
  );
}

// ----------------------------------------------------------- Folder group
function FolderGroup({ g, collapsed, showAll, onToggle, onShowAll, selectedId, onSelect }) {
  const comp = g.all.reduce((a, r) => { a[r.verdict]++; return a; }, { BLOCK: 0, REVIEW: 0, APPROVE: 0 });
  const total = g.all.length;
  const seg = (n) => `${(n / total) * 100}%`;
  const display = showAll ? g.items : g.items.slice(0, CAP);
  const more = g.items.length - display.length;
  const Icon = g.campaign.isInbox ? Inbox : Layers;
  return (
    <div>
      <button onClick={onToggle} className="cf-folder-row w-full flex items-center gap-2" style={{ padding: "9px 12px", background: collapsed ? "transparent" : "#0e1729" }}
        title={`${comp.BLOCK} block · ${comp.REVIEW} review · ${comp.APPROVE} approve`}>
        <ChevronDown size={13} color="#64748b" style={{ transform: collapsed ? "rotate(-90deg)" : "none", transition: "transform .15s", flexShrink: 0 }} />
        <Icon size={13} color={g.campaign.isInbox ? "#94a3b8" : "#34d399"} style={{ flexShrink: 0 }} />
        <span className="truncate" style={{ fontSize: 12, fontWeight: 600, color: "#cbd5e1", flex: 1, textAlign: "left" }}>{g.campaign.name}</span>
        <div className="flex rounded overflow-hidden" style={{ width: 56, height: 6, background: "#1e293b", flexShrink: 0 }}>
          {comp.BLOCK > 0 && <div style={{ width: seg(comp.BLOCK), background: VERDICT.BLOCK.color, opacity: 0.85 }} />}
          {comp.REVIEW > 0 && <div style={{ width: seg(comp.REVIEW), background: VERDICT.REVIEW.color, opacity: 0.85 }} />}
          {comp.APPROVE > 0 && <div style={{ width: seg(comp.APPROVE), background: VERDICT.APPROVE.color, opacity: 0.7 }} />}
        </div>
        <span style={{ fontSize: 10.5, color: "#475569", minWidth: 18, textAlign: "right", flexShrink: 0 }}>{total}</span>
      </button>
      {!collapsed && (
        <div style={{ paddingBottom: 4 }}>
          {display.map((i) => <RailRow key={i.id} item={i} active={i.id === selectedId} onClick={() => onSelect(i.id)} indent />)}
          {more > 0 && <button onClick={onShowAll} style={{ padding: "6px 0 8px 34px", fontSize: 11, color: "#22d3ee" }}>+ {more} more</button>}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------- Rail row
function RailRow({ item, active, onClick, showCampaign, cmpName, indent }) {
  const pad = indent ? "8px 12px 8px 22px" : "9px 12px 9px 14px";
  if (item._job) {
    const stageIdx = Math.min(item.stage, PIPELINE.length - 1);
    return (
      <button onClick={onClick} className={`cf-rail-row w-full text-left flex items-center gap-2.5${active ? " active" : ""}`} style={{ padding: pad, borderLeft: `2px solid ${active ? "#22d3ee" : "transparent"}`, background: active ? "#111a2e" : "transparent" }}>
        <Loader2 size={15} color="#22d3ee" className="animate-spin" style={{ flexShrink: 0 }} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="truncate" style={{ fontSize: 12.5, fontWeight: 500 }}>{item.file}</div>
          <div className="truncate" style={{ fontSize: 10.5, color: "#22d3ee" }}>{item.error ? "failed" : PIPELINE[stageIdx].label + "…"}</div>
        </div>
      </button>
    );
  }
  const cfg = VERDICT[item.verdict];
  return (
    <button onClick={onClick} className={`cf-rail-row w-full text-left flex items-center gap-2.5${active ? " active" : ""}`} style={{ padding: pad, borderLeft: `2px solid ${active ? cfg.color : cfg.color + "33"}`, background: active ? "#111a2e" : "transparent" }}>
      <div className="rounded" style={{ width: 40, height: 23, flexShrink: 0, background: `hsl(${item.hue} 45% 18%)`, border: `1px solid hsl(${item.hue} 30% 28%)` }} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="truncate" style={{ fontSize: 12.5, fontWeight: 600 }}>{item.creator}</div>
        <div className="truncate" style={{ fontSize: 10.5, color: "#475569" }}>{showCampaign ? cmpName(item.campaignId) : item.file}</div>
      </div>
      <div style={{ width: 6, height: 6, borderRadius: 99, background: cfg.color, flexShrink: 0, opacity: active ? 1 : 0.7 }} />
    </button>
  );
}

// ------------------------------------------------------- Center: video
function VideoInspector({ v, cmpName }) {
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [activeEv, setActiveEv] = useState(null);
  const timer = useRef(null);
  const markers = v.policies.filter((p) => p.status === "flagged").flatMap((p) => p.evidence.map((e) => ({ ...e, policy: p.label, contribution: p.contribution })));

  useEffect(() => { setTime(0); setPlaying(false); setActiveEv(null); }, [v.id]);
  useEffect(() => {
    if (playing) timer.current = setInterval(() => setTime((t) => (t >= v.duration ? (setPlaying(false), v.duration) : +(t + 0.2).toFixed(1))), 90);
    return () => clearInterval(timer.current);
  }, [playing, v.duration]);
  const seek = (t, k = null) => { setTime(t); setActiveEv(k); };
  const live = markers.find((m) => time >= m.start && time <= m.end);

  return (
    <>
      <div className="rounded-xl" style={{ border: "1px solid #1e293b", background: "#0b1220", padding: 16 }}>
        <div className="flex items-center gap-2" style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}><Sparkles size={13} /> Auto-generated description</div>
        <p style={{ fontSize: 13.5, lineHeight: 1.65, color: "#cbd5e1" }}>{v.description}</p>
      </div>
      <div className="rounded-xl overflow-hidden relative mt-4" style={{ border: "1px solid #1e293b" }}>
        <div className="relative flex items-center justify-center" style={{ height: 320, background: `radial-gradient(120% 120% at 50% 30%, hsl(${v.hue} 40% 26%), #0b1220 70%)` }}>
          <div style={{ textAlign: "center", opacity: 0.9 }}>
            <div style={{ fontSize: 12, color: "#cbd5e1", letterSpacing: "0.05em" }}>{v.creator}</div>
            <div className="flex items-center justify-center gap-1" style={{ fontSize: 10.5, color: "#64748b", marginTop: 4 }}><Layers size={11} /> {cmpName(v.campaignId)}</div>
            <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>preview frame &middot; {fmt(time)}</div>
          </div>
          {live && <div className="absolute left-1/2" style={{ bottom: 18, transform: "translateX(-50%)", background: VERDICT[live.contribution].color, color: "#020617", fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 7, whiteSpace: "nowrap", boxShadow: "0 4px 18px rgba(0,0,0,0.4)" }}>{live.policy}: {live.label}</div>}
        </div>
        <div style={{ background: "#0b1220", padding: "12px 16px" }}>
          <div className="flex items-center gap-3">
            <button onClick={() => setPlaying((p) => !p)} className="flex items-center justify-center rounded-full" style={{ width: 34, height: 34, background: "#1e293b", flexShrink: 0 }}>{playing ? <Pause size={15} color="#e2e8f0" /> : <Play size={15} color="#e2e8f0" style={{ marginLeft: 2 }} />}</button>
            <span className="mono" style={{ fontSize: 12, color: "#94a3b8", width: 84 }}>{fmt(time)} / {fmt(v.duration)}</span>
            <div className="relative flex-1 rounded cursor-pointer" style={{ height: 34, background: "#111a2e", border: "1px solid #1e293b" }} onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek(+(((e.clientX - r.left) / r.width) * v.duration).toFixed(1)); }}>
              {markers.map((m, i) => { const c = VERDICT[m.contribution], key = `${m.policy}-${i}`; return <div key={key} title={m.label} onClick={(e) => { e.stopPropagation(); seek(m.start, key); }} className="absolute top-0 bottom-0" style={{ left: `${(m.start / v.duration) * 100}%`, width: `${Math.max(2.5, ((m.end - m.start) / v.duration) * 100)}%`, background: c.color, opacity: activeEv === key || (time >= m.start && time <= m.end) ? 0.95 : 0.55, borderRadius: 3, boxShadow: activeEv === key ? `0 0 0 2px ${c.color}` : "none" }} />; })}
              <div className="absolute top-0 bottom-0" style={{ left: `${(time / v.duration) * 100}%`, width: 2, background: "#e2e8f0" }} />
            </div>
          </div>
          {markers.length === 0 && <div style={{ fontSize: 11, color: "#475569", marginTop: 8, paddingLeft: 49 }}>{v.offBriefGate ? "Stopped at the relevance gate. No compliance probes were run." : "No flagged moments. Clean across the full timeline."}</div>}
        </div>
      </div>
    </>
  );
}

// ------------------------------------------------- Center: chat with video
// Conversational Q&A over the creative. In demo mode answers are synthesised
// from the decision data; in a live build this calls TwelveLabs Pegasus
// (/analyze open-ended) for the indexed video via POST /api/reviews/{id}/ask.
function mockAnswer(qRaw, v) {
  const q = qRaw.toLowerCase();
  const flagged = v.policies.filter((p) => p.status === "flagged");
  const ev = flagged.flatMap((p) => p.evidence.map((e) => ({ ...e, policy: p.label })));
  if (/where|when|timestamp|moment|clip/.test(q)) {
    if (!ev.length) return v.offBriefGate ? "Nothing was timestamped — this creative was stopped at the relevance gate before deep analysis ran." : "No flagged moments. The creative is clean across the full timeline.";
    return "Flagged moments:\n" + ev.map((e) => `• ${fmt(e.start)}–${fmt(e.end)} — ${e.policy}: ${e.label} (${e.confidence} confidence)`).join("\n");
  }
  if (/on.?brief|relevan/.test(q)) return `Relevance score is ${v.relevance.toFixed(2)} and the model judged it ${v.onBrief ? "on-brief" : "OFF-brief"}. ${v.onBrief ? "It passed the relevance gate." : "It was rejected at the relevance gate."}`;
  if (/why|reason|verdict|decision|block|approv|review/.test(q)) return `Verdict: ${v.verdict} (${v.confidence} confidence).\n` + v.reasons.map((r) => `• ${r}`).join("\n");
  if (/safe|risk|brand|garm/.test(q)) return flagged.length ? `${flagged.length} policy area(s) triggered: ${flagged.map((p) => p.label).join(", ")}. The most serious drives the ${v.verdict} verdict.` : "No brand-safety risks detected across the GARM floor categories.";
  if (/summar|what happens|describe/.test(q)) return v.description;
  return `Here's what I can tell from the analysis: ${v.description.split(".")[0]}. Ask about timestamps, the verdict, on-brief status, or specific policies.`;
}
const SUGGESTED = ["Where are the flagged moments?", "Why this verdict?", "Is it on-brief?"];

// Chat docked at the bottom of the center pane. The input sits at the very
// bottom; answers populate upward. A drag handle on the top edge lets the
// reviewer resize the chat vs. the video above it.
function ChatDock({ v, topRef, setTopH, live }) {
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const bodyRef = useRef(null);
  useEffect(() => { setMsgs([]); setInput(""); setThinking(false); }, [v.id]);
  useEffect(() => { bodyRef.current?.scrollTo({ top: 1e6, behavior: "smooth" }); }, [msgs, thinking]);

  const ask = (text) => {
    const qq = text.trim(); if (!qq || thinking) return;
    setMsgs((m) => [...m, { role: "user", text: qq }]); setInput(""); setThinking(true);
    if (live) {
      // Real: TwelveLabs Pegasus open-ended analysis of the indexed video.
      jpost(`/api/reviews/${v.id}/ask`, { question: qq })
        .then((a) => setMsgs((m) => [...m, { role: "ai", text: a.answer }]))
        .catch(() => setMsgs((m) => [...m, { role: "ai", text: "Couldn't reach the analysis service for this video." }]))
        .finally(() => setThinking(false));
    } else {
      setTimeout(() => { setMsgs((m) => [...m, { role: "ai", text: mockAnswer(qq, v) }]); setThinking(false); }, 650);
    }
  };

  // Resize by adjusting the height of the content region above; the chat fills
  // whatever is left, so there is never dead space between the video and the chat.
  const startResize = (e) => {
    e.preventDefault();
    const startY = e.clientY;
    const startTop = topRef.current?.offsetHeight ?? 320;
    const avail = (topRef.current?.parentElement?.offsetHeight ?? 800) - 180;
    const move = (ev) => setTopH(Math.max(120, Math.min(avail, startTop + (ev.clientY - startY))));
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); document.body.style.userSelect = ""; };
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };

  const empty = msgs.length === 0 && !thinking;
  return (
    <div style={{ flex: "1 1 0", minHeight: 160, flexShrink: 1, borderTop: "1px solid #1e293b", background: "#0b1220", display: "flex", flexDirection: "column" }}>
      {/* drag handle */}
      <div onMouseDown={startResize} title="Drag to resize" className="flex items-center justify-center" style={{ height: 14, cursor: "row-resize", flexShrink: 0 }}>
        <div style={{ width: 36, height: 4, borderRadius: 99, background: "#334155" }} />
      </div>
      {/* header */}
      <div className="flex items-center justify-between" style={{ padding: "2px 16px 8px", flexShrink: 0 }}>
        <div className="flex items-center gap-2" style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em" }}><MessageSquare size={13} /> Ask about this video</div>
        <span style={{ fontSize: 10, color: "#475569" }}>TwelveLabs · Pegasus</span>
      </div>
      {/* messages (grow + scroll) */}
      <div ref={bodyRef} className="cf-scroll" style={{ flex: 1, overflowY: "auto", padding: "0 16px", display: "flex", flexDirection: "column", gap: 10, minHeight: 0 }}>
        {empty && (
          <div className="flex items-center justify-center" style={{ flex: 1, color: "#475569", fontSize: 12.5 }}>Ask anything about this creative — it reads the video, speech and on-screen text.</div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className="flex" style={{ justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
            <div style={{ maxWidth: "80%", whiteSpace: "pre-wrap", fontSize: 12.5, lineHeight: 1.5, padding: "8px 11px", borderRadius: 10, background: m.role === "user" ? "#1e293b" : "#0e1729", border: m.role === "user" ? "none" : "1px solid #14203a", color: m.role === "user" ? "#e2e8f0" : "#cbd5e1" }}>{m.text}</div>
          </div>
        ))}
        {thinking && <div className="flex items-center gap-1.5" style={{ fontSize: 12, color: "#64748b" }}><Loader2 size={13} className="animate-spin" /> analysing the video…</div>}
      </div>
      {/* input pinned to the bottom */}
      <div style={{ padding: "10px 16px 14px", flexShrink: 0 }}>
        {empty && (
          <div className="flex items-center gap-1.5" style={{ marginBottom: 9, flexWrap: "wrap" }}>
            {SUGGESTED.map((s) => <button key={s} onClick={() => ask(s)} style={{ fontSize: 11, color: "#94a3b8", background: "#0e1729", border: "1px solid #1e293b", borderRadius: 99, padding: "4px 10px" }}>{s}</button>)}
          </div>
        )}
        <div className="flex items-center gap-2 rounded-lg" style={{ background: "#0e1729", border: "1px solid #1e293b", padding: "7px 8px 7px 12px" }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask(input)} placeholder="Ask anything about this creative…"
            style={{ background: "transparent", border: "none", outline: "none", color: "#e2e8f0", fontSize: 12.5, flex: 1, minWidth: 0 }} />
          <button onClick={() => ask(input)} disabled={!input.trim()} className="flex items-center justify-center rounded-md" style={{ width: 30, height: 28, flexShrink: 0, background: input.trim() ? "linear-gradient(135deg,#34d399,#22d3ee)" : "#1e293b", color: input.trim() ? "#020617" : "#475569" }}><Send size={14} /></button>
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------- Center: live pipeline
function JobInspector({ job, cmpName }) {
  const stageIdx = Math.min(job.stage, PIPELINE.length - 1);
  return (
    <div className="rounded-xl" style={{ border: "1px solid #1e293b", background: "#0b1220", padding: 22 }}>
      <div className="flex items-center gap-2.5" style={{ marginBottom: 4 }}><Film size={16} color="#475569" /><span style={{ fontSize: 15, fontWeight: 600 }}>{job.file}</span></div>
      <div className="flex items-center gap-1" style={{ fontSize: 11, color: "#64748b", marginBottom: 22 }}><Layers size={11} /> {cmpName(job.campaignId)}</div>
      <StageStepper stage={job.stage} done={job.done} gated={job.gated} error={job.error} big />
      <div className="flex items-center gap-2" style={{ marginTop: 18, fontSize: 13, color: "#cbd5e1" }}>
        {!job.done && <Loader2 size={14} color="#22d3ee" className="animate-spin" />}
        <span style={{ fontWeight: 500 }}>{job.error ? "Pipeline error" : job.done ? "Finishing…" : PIPELINE[stageIdx].label}</span>
      </div>
      <div style={{ fontSize: 12, color: "#64748b", marginTop: 6 }}>{job.error ? "See logs." : PIPELINE[stageIdx].detail}</div>
    </div>
  );
}

function CenterEmpty({ onUpload }) {
  return (
    <div className="flex flex-col items-center justify-center" style={{ height: "100%", color: "#475569" }}>
      <div className="cf-empty-icon flex items-center justify-center rounded-2xl" style={{ width: 72, height: 72, background: "rgba(52,211,153,0.07)", border: "1px solid rgba(52,211,153,0.15)" }}>
        <Film size={32} color="rgba(52,211,153,0.6)" />
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, marginTop: 16, color: "#94a3b8", letterSpacing: "-0.01em" }}>Select a creative to review</div>
      <div style={{ fontSize: 12.5, color: "#475569", marginTop: 5 }}>or upload a new batch to get started</div>
      <button onClick={onUpload} className="cf-upload-btn flex items-center gap-2 rounded-lg" style={{ marginTop: 18, background: "linear-gradient(135deg,#34d399,#22d3ee)", color: "#020617", fontSize: 13, fontWeight: 700, padding: "9px 18px", border: "none" }}>
        <UploadCloud size={15} color="#020617" /> Upload creatives
      </button>
    </div>
  );
}

// ---------------------------------------------------------- Right panels
function DecisionPanel({ v, decided, onDecide, onUndo }) {
  const cfg = VERDICT[v.verdict];
  return (
    <>
      <div style={{ padding: 18, borderBottom: "1px solid #1e293b" }}>
        <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>Decision</div>
        <div className={`flex items-center gap-3 rounded-xl cf-verdict-${v.verdict.toLowerCase()}`} style={{ background: cfg.soft, padding: "14px 16px" }}>
          <cfg.Icon size={26} color={cfg.color} />
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: cfg.color, letterSpacing: "-0.02em" }}>{v.verdict}</div>
            <div style={{ fontSize: 11.5, color: "#94a3b8" }}>{v.verdict === "APPROVE" ? "Cleared to run as a paid ad" : v.verdict === "REVIEW" ? "Held for human review" : "Not eligible to run"}</div>
          </div>
        </div>
      </div>
      <div style={{ padding: "0 18px 18px" }}>
        <div className="grid grid-cols-3 gap-2" style={{ margin: "16px 0" }}>
          <Stat label="Confidence" value={v.confidence} /><Stat label="Relevance" value={v.relevance.toFixed(2)} dim={!v.onBrief} /><Stat label="On-brief" value={v.onBrief ? "yes" : "no"} dim={!v.onBrief} />
        </div>
        <SectionLabel>Why this decision</SectionLabel>
        <ul style={{ marginBottom: 18 }}>{v.reasons.map((r, i) => <li key={i} className="flex gap-2" style={{ fontSize: 12.5, color: "#cbd5e1", lineHeight: 1.55, marginBottom: 7 }}><ChevronRight size={14} style={{ marginTop: 2, flexShrink: 0, color: cfg.color }} /><span>{r}</span></li>)}</ul>
        <SectionLabel>Policy checks</SectionLabel>
        <div style={{ marginBottom: 18 }}>{v.policies.map((p) => <PolicyRow key={p.id} p={p} />)}</div>

        {decided ? (
          <>
            <SectionLabel>Outcome</SectionLabel>
            <OutcomeCard action={decided} onUndo={() => onUndo(v.id)} />
          </>
        ) : (
          <>
            <SectionLabel>{v.verdict === "REVIEW" ? "Reviewer action" : "Override"}</SectionLabel>
            <div className="flex gap-2" style={{ marginTop: 8 }}>
              <button onClick={() => onDecide(v.id, "APPROVE")} className="cf-action-approve flex-1 rounded-lg flex items-center justify-center gap-1.5" style={{ background: VERDICT.APPROVE.soft, color: VERDICT.APPROVE.color, fontSize: 12.5, fontWeight: 600, padding: "9px 0", border: "1px solid transparent" }}>
                <CheckCircle2 size={14} /> Approve
              </button>
              <button onClick={() => onDecide(v.id, "BLOCK")} className="cf-action-block flex-1 rounded-lg flex items-center justify-center gap-1.5" style={{ background: VERDICT.BLOCK.soft, color: VERDICT.BLOCK.color, fontSize: 12.5, fontWeight: 600, padding: "9px 0", border: "1px solid transparent" }}>
                <XCircle size={14} /> Block
              </button>
            </div>
            {v.humanReview && <div className="flex items-center gap-2 rounded-lg" style={{ marginTop: 10, padding: "8px 10px", background: "rgba(251,191,36,0.08)", fontSize: 11.5, color: "#fbbf24" }}><UserCheck size={14} /> Routed to a human. The system did not auto-decide on uncertainty.</div>}
          </>
        )}
      </div>
    </>
  );
}

// What actually happens after a reviewer commits a call — fills the panel with
// the real downstream consequences instead of a transient toast.
function OutcomeCard({ action, onUndo }) {
  const approve = action === "APPROVE";
  const c = approve ? VERDICT.APPROVE : VERDICT.BLOCK;
  const steps = approve
    ? [{ done: true, t: "Cleared to run as a paid ad" }, { done: false, t: "Queued to the ad server" }, { done: false, t: "Creator notified — live in ~15 min" }, { done: true, t: "Logged to the audit trail" }]
    : [{ done: true, t: "Removed from delivery" }, { done: false, t: "Creator notified with the flagged reasons" }, { done: false, t: "Appeal window open · 7 days" }, { done: true, t: "Logged to the audit trail" }];
  return (
    <div className="rounded-xl" style={{ marginTop: 8, border: `1px solid ${c.soft.replace("0.12", "0.25")}`, background: c.soft, padding: 14 }}>
      <div className="flex items-center gap-2.5" style={{ marginBottom: 12 }}>
        <c.Icon size={20} color={c.color} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: c.color }}>{approve ? "Approved" : "Blocked"} by Subash Natarajan</div>
          <div style={{ fontSize: 11, color: "#94a3b8" }}>just now · recorded alongside the automated verdict</div>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        {steps.map((s, i) => (
          <div key={i} className="flex items-center gap-2" style={{ fontSize: 12, color: s.done ? "#cbd5e1" : "#94a3b8" }}>
            {s.done ? <Check size={14} color={c.color} style={{ flexShrink: 0 }} /> : <Clock size={13} color="#64748b" style={{ flexShrink: 0 }} />}
            <span>{s.t}</span>
          </div>
        ))}
      </div>
      <button onClick={onUndo} className="w-full rounded-lg" style={{ marginTop: 13, padding: "7px 0", background: "transparent", border: "1px solid #1e293b", color: "#94a3b8", fontSize: 12, fontWeight: 500 }}>Undo / change decision</button>
    </div>
  );
}

function JobDecision() {
  return (
    <div style={{ padding: 18 }}>
      <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>Decision</div>
      <div className="flex items-center gap-3 rounded-xl" style={{ background: "rgba(34,211,238,0.10)", padding: "14px 16px" }}>
        <Loader2 size={22} color="#22d3ee" className="animate-spin" />
        <div><div style={{ fontSize: 15, fontWeight: 700, color: "#22d3ee" }}>Processing</div><div style={{ fontSize: 11.5, color: "#94a3b8" }}>The verdict appears here when the pipeline finishes.</div></div>
      </div>
      <div style={{ fontSize: 11.5, color: "#475569", marginTop: 16, lineHeight: 1.6 }}>No language model makes the final call. Once perception completes, the deterministic engine produces an auditable APPROVE / REVIEW / BLOCK.</div>
    </div>
  );
}

// ---------------------------------------------------------- Upload modal
function UploadModal({ campaigns, reviews, initialNew, onClose, createCampaign, onIntake, onIntakeUrl, showToast }) {
  const real = campaigns.filter((c) => !c.isInbox);
  const [mode, setMode] = useState(initialNew || !real.length ? "new" : "existing");
  const [campaignId, setCampaignId] = useState(campaigns[0]?.id || "");
  const [name, setName] = useState(""); const [brief, setBrief] = useState("");
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);

  const resolveCampaign = async () => (mode === "new" ? (name.trim() ? (await createCampaign(name, brief)).id : null) : campaignId);
  const go = async (files) => { const cid = await resolveCampaign(); if (!cid) return; await onIntake(files, cid); onClose(); };
  const onDrop = (e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) go(e.dataTransfer.files); };
  const ready = mode === "new" ? !!name.trim() : !!campaignId;

  return (
    <div className="fixed inset-0 flex items-center justify-center" style={{ background: "rgba(2,6,23,0.7)", zIndex: 50 }} onClick={onClose}>
      <div className="rounded-2xl" style={{ width: 540, maxWidth: "92vw", background: "#0b1220", border: "1px solid #1e293b", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-2"><UploadCloud size={17} color="#34d399" /><span style={{ fontSize: 16, fontWeight: 600 }}>{mode === "new" ? "New campaign" : "Add creatives"}</span></div>
          <button onClick={onClose}><X size={18} color="#64748b" /></button>
        </div>

        <div className="flex items-center gap-2" style={{ marginBottom: 10 }}>
          <button onClick={() => setMode("existing")} disabled={!real.length} className="rounded-lg" style={{ fontSize: 12, padding: "6px 11px", background: mode === "existing" ? "#1e293b" : "transparent", color: mode === "existing" ? "#e2e8f0" : "#64748b", border: "1px solid #1e293b", opacity: real.length ? 1 : 0.4 }}>Existing campaign</button>
          <button onClick={() => setMode("new")} className="flex items-center gap-1 rounded-lg" style={{ fontSize: 12, padding: "6px 11px", background: mode === "new" ? "#1e293b" : "transparent", color: mode === "new" ? "#e2e8f0" : "#64748b", border: "1px solid #1e293b" }}><Plus size={12} /> New campaign</button>
        </div>

        {mode === "existing" ? (
          <select value={campaignId} onChange={(e) => setCampaignId(e.target.value)} style={{ width: "100%", background: "#0e1729", border: "1px solid #1e293b", borderRadius: 9, color: "#e2e8f0", fontSize: 13, padding: "10px 12px", outline: "none" }}>
            {campaigns.map((c) => <option key={c.id} value={c.id} style={{ color: "#000" }}>{c.isInbox ? "📥 Unsorted (single / quick check)" : `${c.name} · ${reviews.filter((r) => r.campaignId === c.id).length} creatives`}</option>)}
          </select>
        ) : (
          <>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Campaign name (e.g. Summer Glow 2026)" style={{ width: "100%", background: "#0e1729", border: "1px solid #1e293b", borderRadius: 9, color: "#e2e8f0", fontSize: 13, padding: "10px 12px", outline: "none" }} />
            <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={2} placeholder="Campaign brief — used by the relevance gate." style={{ width: "100%", marginTop: 8, background: "#0e1729", border: "1px solid #1e293b", borderRadius: 9, color: "#e2e8f0", fontSize: 13, padding: "10px 12px", outline: "none", resize: "vertical", fontFamily: "inherit" }} />
          </>
        )}

        {/* drop zone */}
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
          onClick={() => ready && inputRef.current?.click()}
          className="rounded-xl flex flex-col items-center justify-center" style={{ marginTop: 14, padding: "30px 0", border: `1.5px dashed ${drag ? "#34d399" : "#243049"}`, background: drag ? "rgba(52,211,153,0.06)" : "#0e1729", cursor: ready ? "pointer" : "not-allowed", opacity: ready ? 1 : 0.5 }}>
          <UploadCloud size={26} color={drag ? "#34d399" : "#64748b"} />
          <div style={{ fontSize: 13.5, fontWeight: 500, marginTop: 10 }}>{ready ? "Drop video files here, or click to browse" : "Pick or name a campaign first"}</div>
          <div style={{ fontSize: 11.5, color: "#64748b", marginTop: 4 }}>One file or a whole batch · MP4, MOV, WebM</div>
          <input ref={inputRef} type="file" accept="video/*" multiple style={{ display: "none" }} onChange={(e) => e.target.files.length && go(e.target.files)} />
        </div>

        <div style={{ fontSize: 11, color: "#475569", marginTop: 12 }}>Drop a whole batch — each video is reviewed independently and streams into the queue. Stored in your {`Clearframe`} bucket (Supabase) when connected, local disk otherwise.</div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------- Settings
function SettingsModal({ onClose, showToast, live }) {
  const [workspace, setWorkspace] = useState("Lumiere Cosmetics");
  const [defaultView, setDefaultView] = useState("NEEDS");
  const [density, setDensity] = useState("comfortable");
  const [savedKey, setSavedKey] = useState(() => { try { return live ? "" : (localStorage.getItem("tl_api_key") || ""); } catch { return ""; } });
  const [remoteConnected, setRemoteConnected] = useState(false);
  const [remoteMasked, setRemoteMasked] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [reveal, setReveal] = useState(false);
  useEffect(() => { if (live) jget("/api/settings").then((s) => { setRemoteConnected(!!s.twelvelabs_connected); setRemoteMasked(s.masked_key || ""); }).catch(() => {}); }, []);
  const mask = (k) => (k.length > 8 ? k.slice(0, 4) + "••••••••" + k.slice(-4) : "••••••••");
  const hasKey = live ? remoteConnected : !!savedKey;
  const maskedView = live ? remoteMasked : mask(savedKey);
  const saveKey = async () => {
    const k = apiKey.trim(); if (!k) return;
    if (live) {
      try { const s = await jpost("/api/settings/twelvelabs-key", { api_key: k }); setRemoteConnected(!!s.twelvelabs_connected); setRemoteMasked(s.masked_key || ""); showToast?.("TwelveLabs key saved & verified"); }
      catch (e) { showToast?.(String(e.message || e).slice(0, 160)); return; }
    } else { try { localStorage.setItem("tl_api_key", k); } catch {} setSavedKey(k); showToast?.("Key saved (demo · stored locally)"); }
    setApiKey(""); setReveal(false);
  };
  const removeKey = async () => {
    if (live) { try { await fetch(`${API_BASE}/api/settings/twelvelabs-key`, { method: "DELETE" }); } catch {} setRemoteConnected(false); setRemoteMasked(""); }
    else { try { localStorage.removeItem("tl_api_key"); } catch {} setSavedKey(""); }
    showToast?.("Key removed");
  };
  const Row = ({ label, hint, children }) => (
    <div className="flex items-center justify-between" style={{ padding: "12px 0", borderTop: "1px solid #14203a" }}>
      <div style={{ minWidth: 0, paddingRight: 16 }}><div style={{ fontSize: 13, color: "#e2e8f0" }}>{label}</div>{hint && <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{hint}</div>}</div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
  const sel = { background: "#0e1729", border: "1px solid #1e293b", borderRadius: 8, color: "#e2e8f0", fontSize: 12.5, padding: "7px 10px", outline: "none" };
  return (
    <div className="fixed inset-0 flex items-center justify-center" style={{ background: "rgba(2,6,23,0.7)", zIndex: 50 }} onClick={onClose}>
      <div className="rounded-2xl cf-scroll" style={{ width: 560, maxWidth: "92vw", maxHeight: "86vh", overflowY: "auto", background: "#0b1220", border: "1px solid #1e293b", padding: 22 }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between" style={{ marginBottom: 18 }}>
          <div className="flex items-center gap-2"><Settings size={17} color="#34d399" /><span style={{ fontSize: 16, fontWeight: 600 }}>Settings</span></div>
          <button onClick={onClose}><X size={18} color="#64748b" /></button>
        </div>

        {/* Profile */}
        <div className="flex items-center gap-3" style={{ marginBottom: 8 }}>
          <div className="flex items-center justify-center rounded-full" style={{ width: 44, height: 44, background: "linear-gradient(135deg,#6366f1,#22d3ee)", color: "#020617", fontSize: 15, fontWeight: 700 }}>SN</div>
          <div><div style={{ fontSize: 14, fontWeight: 600 }}>Subash Natarajan</div><div style={{ fontSize: 11.5, color: "#64748b" }}>Compliance lead · admin</div></div>
        </div>

        {/* TwelveLabs key — first, it's the most important setting */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "16px 0 8px" }}>
          <div className="flex items-center gap-2"><Key size={14} color="#22d3ee" /><span style={{ fontSize: 12.5, fontWeight: 600, color: "#e2e8f0" }}>TwelveLabs API key</span></div>
          <span className="flex items-center gap-1.5" style={{ fontSize: 10.5, fontWeight: 700, color: hasKey ? "#34d399" : "#64748b", background: hasKey ? "rgba(52,211,153,0.12)" : "#1e293b", padding: "3px 9px", borderRadius: 99 }}>
            <span style={{ width: 6, height: 6, borderRadius: 99, background: hasKey ? "#34d399" : "#64748b" }} /> {hasKey ? "Connected" : "Not connected"}
          </span>
        </div>
        {hasKey ? (
          <div className="flex items-center gap-2">
            <code style={{ flex: 1, fontSize: 12.5, fontFamily: "ui-monospace, monospace", color: "#94a3b8", background: "#0e1729", border: "1px solid #1e293b", borderRadius: 8, padding: "9px 10px" }}>{maskedView}</code>
            <button onClick={() => { setRemoteConnected(false); setSavedKey(""); }} className="rounded-lg" style={{ ...sel, cursor: "pointer" }}>Replace</button>
            <button onClick={removeKey} className="rounded-lg" style={{ fontSize: 12, color: "#fb7185", background: "transparent", border: "1px solid rgba(251,113,133,0.3)", borderRadius: 8, padding: "8px 11px" }}>Remove</button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2" style={{ flex: 1, background: "#0e1729", border: "1px solid #1e293b", borderRadius: 8, padding: "7px 8px 7px 10px" }}>
              <input type={reveal ? "text" : "password"} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="Paste your TwelveLabs key (tlk_…)" autoComplete="off"
                style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none", color: "#e2e8f0", fontSize: 12.5, fontFamily: "ui-monospace, monospace" }} />
              <button onClick={() => setReveal((r) => !r)} title={reveal ? "Hide" : "Show"}>{reveal ? <EyeOff size={14} color="#64748b" /> : <Eye size={14} color="#64748b" />}</button>
            </div>
            <button onClick={saveKey} disabled={!apiKey.trim()} className="rounded-lg" style={{ fontSize: 12, fontWeight: 600, color: apiKey.trim() ? "#020617" : "#475569", background: apiKey.trim() ? "linear-gradient(135deg,#34d399,#22d3ee)" : "#1e293b", borderRadius: 8, padding: "9px 16px" }}>Save</button>
          </div>
        )}
        <div className="flex items-start gap-1.5" style={{ marginTop: 9, marginBottom: 4, fontSize: 11, color: "#64748b", lineHeight: 1.5 }}>
          <ShieldCheck size={13} color="#475569" style={{ marginTop: 1, flexShrink: 0 }} />
          <span>Required for real verdicts &amp; chat. {live ? "Validated against TwelveLabs, then encrypted at rest on the server (Fernet) — only a masked preview returns to the browser." : "Demo mode: stored locally. Start the backend to validate + store it encrypted."}</span>
        </div>

        <SectionLabel>Workspace</SectionLabel>
        <Row label="Workspace name" hint="Shown in the header and on exports.">
          <input value={workspace} onChange={(e) => setWorkspace(e.target.value)} style={{ ...sel, width: 200 }} />
        </Row>
        <Row label="Default queue view" hint="What the rail shows on load.">
          <select value={defaultView} onChange={(e) => setDefaultView(e.target.value)} style={sel}><option value="NEEDS" style={{ color: "#000" }}>Needs attention</option><option value="ALL" style={{ color: "#000" }}>All creatives</option></select>
        </Row>
        <Row label="Row density" hint="Compact fits more creatives on screen.">
          <select value={density} onChange={(e) => setDensity(e.target.value)} style={sel}><option value="comfortable" style={{ color: "#000" }}>Comfortable</option><option value="compact" style={{ color: "#000" }}>Compact</option></select>
        </Row>

        <SectionLabel>Compliance</SectionLabel>
        <Row label="Policy taxonomy" hint="GARM-mapped categories & per-advertiser tolerances.">
          <button onClick={() => showToast?.("Policy config — coming in the backend phase")} className="rounded-lg" style={{ ...sel, cursor: "pointer" }}>Open policy config</button>
        </Row>
        <Row label="Connected sources" hint="Google Drive, object storage, upload.">
          <button onClick={() => showToast?.("Source connections — coming in the backend phase")} className="flex items-center gap-1.5 rounded-lg" style={{ ...sel, cursor: "pointer" }}><Cloud size={13} color="#22d3ee" /> Manage</button>
        </Row>

        <div className="flex items-center justify-between" style={{ marginTop: 20 }}>
          <button onClick={() => showToast?.("Signed out (demo)")} style={{ fontSize: 12.5, color: "#fb7185", background: "transparent", border: "1px solid rgba(251,113,133,0.3)", borderRadius: 8, padding: "8px 14px" }}>Sign out</button>
          <button onClick={() => { showToast?.("Settings saved"); onClose(); }} style={{ fontSize: 12.5, fontWeight: 600, color: "#020617", background: "linear-gradient(135deg,#34d399,#22d3ee)", borderRadius: 8, padding: "8px 16px" }}>Save changes</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------- Stage stepper
function StageStepper({ stage, done, gated, error, big }) {
  const skip = gated ? GATED_SKIP : [];
  const sz = big ? 34 : 26, ic = big ? 16 : 13;
  return (
    <div className="flex items-center">
      {PIPELINE.map((p, i) => {
        const skipped = skip.includes(i);
        const isDone = !skipped && (done ? true : i < stage);
        const isActive = !done && !skipped && i === stage;
        const color = error && done ? "#fb7185" : isDone ? "#34d399" : isActive ? "#22d3ee" : "#334155";
        const Icon = skipped ? MinusCircle : isDone ? Check : p.Icon;
        return (
          <React.Fragment key={p.key}>
            <div className="flex flex-col items-center" style={{ flexShrink: 0 }} title={`${p.label} — ${p.detail}`}>
              <div className="flex items-center justify-center rounded-full" style={{ width: sz, height: sz, background: isActive ? "rgba(34,211,238,0.12)" : isDone && !error ? "rgba(52,211,153,0.12)" : "transparent", border: `1.5px solid ${color}`, boxShadow: isActive ? "0 0 0 3px rgba(34,211,238,0.10)" : "none" }}>
                {isActive ? <Loader2 size={ic} color={color} className="animate-spin" /> : <Icon size={ic} color={color} />}
              </div>
              {big && <span style={{ fontSize: 9.5, color, marginTop: 6, width: 64, textAlign: "center", lineHeight: 1.2 }}>{p.label}</span>}
            </div>
            {i < PIPELINE.length - 1 && <div style={{ flex: 1, height: 2, background: (done || i < stage) && !skip.includes(i + 1) ? "#34d399" : "#1e293b", margin: big ? "0 4px" : "0 2px", marginTop: big ? sz / 2 - 1 : 0 }} />}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------- Primitives
function PolicyRow({ p }) {
  if (p.status === "clean") return <div className="flex items-center gap-2" style={{ padding: "6px 0", fontSize: 12.5, color: "#64748b" }}><CheckCircle2 size={15} color="#334155" /><span>{p.label}</span></div>;
  if (p.status === "skipped") return <div className="flex items-center gap-2" style={{ padding: "6px 0", fontSize: 12.5, color: "#3f4a5e" }}><Clock size={15} color="#27313f" /><span>{p.label} <span style={{ fontSize: 10.5 }}>not run</span></span></div>;
  const cfg = VERDICT[p.contribution];
  return (
    <div style={{ padding: "8px 0", borderTop: "1px solid #14203a" }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2" style={{ fontSize: 12.5, fontWeight: 500 }}><AlertTriangle size={15} color={cfg.color} /><span>{p.label}</span></div>
        <span style={{ fontSize: 10, fontWeight: 700, color: cfg.color, background: cfg.soft, padding: "2px 7px", borderRadius: 5 }}>{p.severity}</span>
      </div>
      {p.evidence.map((e, i) => { const MIcon = MODALITY_ICON[e.modality] || Eye; return (
        <div key={i} className="flex items-start gap-2 rounded-md" style={{ marginTop: 6, padding: "7px 9px", background: "#0e1729", border: "1px solid #14203a" }}>
          <MIcon size={13} color={cfg.color} style={{ marginTop: 1, flexShrink: 0 }} />
          <span style={{ fontSize: 11.5, color: "#cbd5e1", lineHeight: 1.45 }}><span style={{ fontFamily: "ui-monospace, monospace", color: cfg.color }}>{fmt(e.start)}</span> {e.label}<span style={{ color: "#64748b" }}> &middot; {e.confidence} confidence</span></span>
        </div>
      ); })}
    </div>
  );
}
function Stat({ label, value, dim }) { return <div className="rounded-lg" style={{ background: "#0e1729", border: "1px solid #14203a", padding: "8px 10px" }}><div style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div><div style={{ fontSize: 14, fontWeight: 600, marginTop: 2, color: dim ? "#fb7185" : "#e2e8f0" }}>{value}</div></div>; }
function SectionLabel({ children }) { return <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", margin: "14px 0 8px" }}>{children}</div>; }
function Pill({ n, c, label }) { return <span className="flex items-center gap-1.5"><span style={{ width: 7, height: 7, borderRadius: 99, background: c, display: "inline-block" }} /><span style={{ color: "#cbd5e1" }}>{n}</span><span style={{ color: "#64748b" }}>{label}</span></span>; }

function KpiChip({ n, verdict }) {
  const cfg = VERDICT[verdict];
  const Icon = cfg.Icon;
  const active = n > 0;
  return (
    <div className="flex items-center gap-1.5 rounded-lg" style={{
      padding: "5px 10px",
      background: active ? cfg.soft : "rgba(30,41,59,0.5)",
      border: `1px solid ${active ? cfg.color + "40" : "#1e293b"}`,
      transition: "all 0.15s ease",
    }}>
      <Icon size={13} color={active ? cfg.color : "#475569"} />
      <span style={{ fontSize: 14, fontWeight: 700, color: active ? cfg.color : "#475569", lineHeight: 1, letterSpacing: "-0.02em" }}>{n}</span>
      <span style={{ fontSize: 10.5, color: active ? cfg.color + "bb" : "#334155", fontWeight: 500 }}>{cfg.label.toLowerCase()}</span>
    </div>
  );
}

// Quiet inline verdict tally — number is the signal, color confirms it, no chrome needed
function VerdictStat({ n, verdict }) {
  const cfg = VERDICT[verdict];
  return (
    <div className="flex items-center gap-1.5">
      <span style={{ fontSize: 16, fontWeight: 700, color: n > 0 ? cfg.color : "#334155", letterSpacing: "-0.03em", lineHeight: 1 }}>{n}</span>
      <span style={{ fontSize: 10.5, fontWeight: 500, color: n > 0 ? "#64748b" : "#283040" }}>{cfg.label.toLowerCase()}</span>
    </div>
  );
}

function ShortcutsModal({ onClose }) {
  const groups = [
    {
      title: "Navigation",
      items: [
        { keys: ["j", "↓"], desc: "Next creative in queue" },
        { keys: ["k", "↑"], desc: "Previous creative in queue" },
        { keys: ["/"], desc: "Focus search bar" },
        { keys: ["Esc"], desc: "Close modals / blur input" },
      ],
    },
    {
      title: "Review actions",
      items: [
        { keys: ["a"], desc: "Approve selected creative" },
        { keys: ["b"], desc: "Block selected creative" },
        { keys: ["u"], desc: "Open upload (to Unsorted)" },
        { keys: ["n"], desc: "New campaign + upload" },
      ],
    },
    {
      title: "Interface",
      items: [
        { keys: ["?"], desc: "Toggle this shortcuts panel" },
      ],
    },
  ];
  return (
    <div className="fixed inset-0 flex items-center justify-center" style={{ background: "rgba(2,6,23,0.75)", zIndex: 60, backdropFilter: "blur(4px)" }} onClick={onClose}>
      <div className="rounded-2xl" style={{ width: 440, maxWidth: "92vw", background: "#0b1220", border: "1px solid #1e293b", overflow: "hidden", boxShadow: "0 24px 64px rgba(0,0,0,0.7)" }} onClick={(e) => e.stopPropagation()}>
        {/* Top bar */}
        <div style={{ background: "linear-gradient(90deg,#34d399 0%,#22d3ee 50%,#6366f1 100%)", height: 2 }} />
        <div className="flex items-center justify-between" style={{ padding: "16px 18px 12px" }}>
          <div className="flex items-center gap-2">
            <Keyboard size={16} color="#34d399" />
            <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: "-0.01em" }}>Keyboard shortcuts</span>
          </div>
          <button onClick={onClose}><X size={16} color="#64748b" /></button>
        </div>

        <div style={{ padding: "0 18px 20px", display: "flex", flexDirection: "column", gap: 20 }}>
          {groups.map((g) => (
            <div key={g.title}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>{g.title}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {g.items.map((item) => (
                  <div key={item.desc} className="flex items-center justify-between" style={{ padding: "6px 10px", borderRadius: 8, background: "#0e1729" }}>
                    <span style={{ fontSize: 12.5, color: "#94a3b8" }}>{item.desc}</span>
                    <div className="flex items-center gap-1">
                      {item.keys.map((k) => (
                        <kbd key={k} style={{ fontSize: 11, fontWeight: 600, color: "#e2e8f0", background: "#1e293b", border: "1px solid #334155", borderBottom: "2px solid #475569", borderRadius: 5, padding: "2px 7px", fontFamily: "ui-monospace, monospace" }}>{k}</kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div style={{ borderTop: "1px solid #1e293b", padding: "10px 18px", fontSize: 11, color: "#334155" }}>
          Press <kbd style={{ fontSize: 10, color: "#64748b", background: "#1e293b", border: "1px solid #334155", borderRadius: 4, padding: "1px 5px" }}>?</kbd> anywhere to toggle this panel
        </div>
      </div>
    </div>
  );
}
// Logomark: a camera viewfinder (four corner brackets = "frame") wrapping a
// clearance check (= "clear"). White motif on an emerald→cyan gradient tile.
function Logo({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="ClearFrame" role="img">
      <defs>
        <linearGradient id="cf-grad" x1="3" y1="2" x2="37" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#4ade80" /><stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="11" fill="url(#cf-grad)" />
      <g stroke="#ffffff" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" fill="none">
        {/* four viewfinder corners */}
        <path d="M11.5 15 V13 Q11.5 11 13.5 11 H15.5" />
        <path d="M28.5 15 V13 Q28.5 11 26.5 11 H24.5" />
        <path d="M11.5 25 V27 Q11.5 29 13.5 29 H15.5" />
        <path d="M28.5 25 V27 Q28.5 29 26.5 29 H24.5" />
        {/* clearance check */}
        <path d="M15.8 20.4 l2.9 2.9 l5.5 -6.1" strokeWidth="2.6" />
      </g>
    </svg>
  );
}
function Kbd({ children }) { return <kbd style={{ fontSize: 10, color: "#94a3b8", border: "1px solid #1e293b", borderRadius: 4, padding: "0px 4px", margin: "0 1px", background: "#0e1729" }}>{children}</kbd>; }
function Empty({ text }) { return <div style={{ padding: "28px 16px", textAlign: "center", fontSize: 12.5, color: "#475569" }}>{text}</div>; }
