import React, { useState, useEffect, useRef, useMemo } from "react";
import {
  FileCheck, UploadCloud, CheckCircle2, AlertTriangle, XCircle, Play, Pause,
  Eye, Mic, ChevronRight, ChevronLeft, Sparkles, UserCheck, Search, Download,
  Loader2, Film, ArrowUpDown, X
} from "lucide-react";

// ---------------------------------------------------------------------------
// Clearframe: bulk-upload + batch-review + detail reviewer.
// Standalone demo mode simulates the pipeline so it runs without a backend.
// Set API_BASE to a running Clearframe API to make uploads and verdicts real.
// ---------------------------------------------------------------------------
const API_BASE = ""; // e.g. "http://localhost:8000" to use the real API
const LIVE = !!API_BASE;

// --- Live API helpers. Used only when API_BASE is set; otherwise the app
// --- runs in self-contained demo mode and these are never called. ---
async function apiUpload(files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const res = await fetch(`${API_BASE}/api/reviews/upload`, { method: "POST", body: fd });
  return (await res.json()).reviews; // [{id, file, status}]
}
async function apiPoll(id) {
  for (let i = 0; i < 60; i++) {
    const r = await (await fetch(`${API_BASE}/api/reviews/${id}`)).json();
    if (r.status === "done" || r.status === "failed") return r.result;
    await new Promise((res) => setTimeout(res, 500));
  }
  return null;
}
function hashHue(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }

// Map a backend GreenlightResult into the shape the UI renders. Fields the
// pipeline does not carry (creator handle, duration, thumbnail hue) are
// synthesised here; in a real build they come from the video's own metadata.
function adaptResult(r, file) {
  const policies = (r.policy_verdicts || []).map((p) => ({
    id: p.policy_id, label: p.label,
    status: p.triggered ? "flagged" : "clean",
    severity: p.severity, contribution: p.contribution,
    evidence: (p.evidence || []).map((e) => ({
      start: e.start, end: e.end, confidence: e.confidence, modality: "visual", label: e.query,
    })),
  }));
  return {
    id: newId(), file, campaign: "Lumiere Velvet Matte",
    creator: "@" + file.replace(/\.[^.]+$/, "").replace(/[_-]/g, "."),
    duration: 75, hue: hashHue(file),
    verdict: r.decision, confidence: r.confidence,
    relevance: r.relevance_score ?? 0, onBrief: r.on_brief,
    humanReview: r.human_review_required, description: r.description,
    reasons: r.reasons || [], policies,
    offBriefGate: r.on_brief === false && policies.length === 0,
  };
}

const VERDICT = {
  APPROVE: { color: "#34d399", soft: "rgba(52,211,153,0.12)", label: "Approve", Icon: CheckCircle2 },
  REVIEW:  { color: "#fbbf24", soft: "rgba(251,191,36,0.12)", label: "Review",  Icon: AlertTriangle },
  BLOCK:   { color: "#fb7185", soft: "rgba(251,113,133,0.12)", label: "Block",   Icon: XCircle },
};
const MODALITY_ICON = { visual: Eye, audio: Mic };

const TEMPLATES = {
  clean_tutorial: {
    creator: "@maya.beauty", duration: 75, verdict: "APPROVE", confidence: "high",
    relevance: 0.88, onBrief: true, humanReview: false, hue: 168,
    description: "A creator demonstrates a matte lipstick and foundation from the Lumiere Velvet Matte collection, applying each evenly to the face while narrating the steps. The focus stays on the product throughout.",
    reasons: ["No policy violations detected. On-brief and clean across all categories."],
    policies: [
      { id: "hate", label: "Hate / harassment", status: "clean" },
      { id: "drugs", label: "Drugs / illegal behaviour", status: "clean" },
      { id: "profanity", label: "Profanity", status: "clean" },
      { id: "unsafe", label: "Unsafe product usage", status: "clean" },
      { id: "claims", label: "Medical / cosmetic claims", status: "clean" },
    ],
  },
  eye_misuse_claim: {
    creator: "@priya.glow", duration: 78, verdict: "BLOCK", confidence: "high",
    relevance: 0.82, onBrief: true, humanReview: false, hue: 350,
    description: "A creator demonstrates an eyeliner and serum, applying product onto the inner waterline in a way that touches the eyeball, then stating the serum cures acne and treats rosacea within a week.",
    reasons: ["Unsafe product usage at high severity, corroborated by a timestamped clip.",
      "Medical claim at high severity: a cosmetic cannot claim to cure acne or treat rosacea."],
    policies: [
      { id: "hate", label: "Hate / harassment", status: "clean" },
      { id: "drugs", label: "Drugs / illegal behaviour", status: "clean" },
      { id: "profanity", label: "Profanity", status: "clean" },
      { id: "unsafe", label: "Unsafe product usage", status: "flagged", severity: "high", contribution: "BLOCK",
        evidence: [{ start: 34, end: 42, confidence: "high", modality: "visual", label: "Product applied onto the eyeball and inner waterline" }] },
      { id: "claims", label: "Medical / cosmetic claims", status: "flagged", severity: "high", contribution: "BLOCK",
        evidence: [{ start: 57, end: 61, confidence: "high", modality: "audio", label: "Claims the serum cures acne and treats rosacea" }] },
    ],
  },
  mild_profanity: {
    creator: "@jordan.grwm", duration: 70, verdict: "REVIEW", confidence: "high",
    relevance: 0.86, onBrief: true, humanReview: true, hue: 41,
    description: "A get ready with me routine using the matte foundation and lipstick, shown clearly on the face. At one point the creator uses a single mild swear word reacting to a smudge, then continues normally.",
    reasons: ["Profanity at low severity: below the block threshold, above the review threshold.",
      "Limited profanity tolerance for this advertiser routes a single instance to a human."],
    policies: [
      { id: "hate", label: "Hate / harassment", status: "clean" },
      { id: "drugs", label: "Drugs / illegal behaviour", status: "clean" },
      { id: "profanity", label: "Profanity", status: "flagged", severity: "low", contribution: "REVIEW",
        evidence: [{ start: 46.5, end: 48, confidence: "medium", modality: "audio", label: "A single mild swear word reacting to a smudge" }] },
      { id: "unsafe", label: "Unsafe product usage", status: "clean" },
      { id: "claims", label: "Medical / cosmetic claims", status: "clean" },
    ],
  },
  offbrief_clickbait: {
    creator: "@dailyvibes", duration: 64, verdict: "BLOCK", confidence: "high",
    relevance: 0.28, onBrief: false, humanReview: false, hue: 280, offBriefGate: true,
    description: "A fast-paced lifestyle vlog of errands, coffee and a short dance. A makeup product appears briefly on a table but is never picked up, named or applied. Most of the runtime is unrelated to cosmetics.",
    reasons: ["Off-brief: relevance 0.28 is below the 0.55 threshold and the model judged it off-brief.",
      "Rejected at the relevance gate before deep compliance analysis ran."],
    policies: [
      { id: "hate", label: "Hate / harassment", status: "skipped" },
      { id: "drugs", label: "Drugs / illegal behaviour", status: "skipped" },
      { id: "profanity", label: "Profanity", status: "skipped" },
      { id: "unsafe", label: "Unsafe product usage", status: "skipped" },
      { id: "claims", label: "Medical / cosmetic claims", status: "skipped" },
    ],
  },
};
const TEMPLATE_KEYS = Object.keys(TEMPLATES);

const fmt = (s) => `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, "0")}`;
let seq = 100;
const newId = () => `rv_${++seq}`;

function makeReview(file, templateKey) {
  const t = TEMPLATES[templateKey];
  return { id: newId(), file, campaign: "Lumiere Velvet Matte", ...t, _key: templateKey };
}
function pickTemplate(filename) {
  const f = filename.toLowerCase();
  const match = TEMPLATE_KEYS.find((k) => f.includes(k.split("_")[0]));
  return match || TEMPLATE_KEYS[Math.floor(Math.random() * TEMPLATE_KEYS.length)];
}

export default function ClearframeApp() {
  const [view, setView] = useState("queue"); // upload | queue | detail
  const [reviews, setReviews] = useState(() =>
    ["clean_tutorial", "eye_misuse_claim", "mild_profanity", "offbrief_clickbait"].map((k) => makeReview(`${k}.mp4`, k))
  );
  const [selectedId, setSelectedId] = useState(null);
  const [toast, setToast] = useState(null);
  const showToast = (m) => { setToast(m); setTimeout(() => setToast(null), 2400); };

  const addReviews = (items) => setReviews((r) => [...items, ...r]);
  const open = (id) => { setSelectedId(id); setView("detail"); };

  return (
    <div style={{ background: "#020617", color: "#e2e8f0", minHeight: "100vh", fontFamily: "ui-sans-serif, system-ui, -apple-system, sans-serif" }}>
      <header className="flex items-center justify-between px-6 py-3 border-b" style={{ borderColor: "#1e293b" }}>
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center rounded-md" style={{ width: 30, height: 30, background: "linear-gradient(135deg,#34d399,#22d3ee)" }}>
            <FileCheck size={17} color="#020617" strokeWidth={2.4} />
          </div>
          <div>
            <div className="font-semibold tracking-tight" style={{ fontSize: 15 }}>Clearframe</div>
            <div style={{ fontSize: 11, color: "#64748b", marginTop: -2 }}>Ad compliance review</div>
          </div>
        </div>
        <nav className="flex items-center gap-1">
          <Tab active={view === "upload"} onClick={() => setView("upload")} icon={UploadCloud}>Upload</Tab>
          <Tab active={view === "queue" || view === "detail"} onClick={() => setView("queue")} icon={Film}>Review queue</Tab>
        </nav>
        <div style={{ fontSize: 12, color: "#64748b" }}>Lumiere Cosmetics &middot; Spring 2026</div>
      </header>

      {view === "upload" && <UploadView onDone={addReviews} goQueue={() => setView("queue")} showToast={showToast} />}
      {view === "queue" && <QueueView reviews={reviews} onOpen={open} goUpload={() => setView("upload")} showToast={showToast} />}
      {view === "detail" && <DetailView review={reviews.find((r) => r.id === selectedId)} back={() => setView("queue")} showToast={showToast} />}

      {toast && (
        <div className="fixed left-1/2" style={{ bottom: 24, transform: "translateX(-50%)", background: "#1e293b", color: "#e2e8f0", fontSize: 13, padding: "10px 16px", borderRadius: 9, boxShadow: "0 8px 30px rgba(0,0,0,0.5)" }}>
          {toast}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------- Upload
const STAGES = ["Uploading", "Indexing", "Analyzing", "Decided"];

function UploadView({ onDone, goQueue, showToast }) {
  const [items, setItems] = useState([]); // {id, file, stage, key}
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);
  const itemsRef = useRef(items);
  itemsRef.current = items;

  const intake = (fileList) => {
    const files = Array.from(fileList);
    if (!files.length) return;
    if (LIVE) return intakeLive(files);
    const fresh = files.map((f) => ({ id: newId(), file: f.name, stage: 0, key: pickTemplate(f.name) }));
    setItems((x) => [...fresh, ...x]);
    // Simulate the async pipeline per file, staggered so verdicts stream in.
    fresh.forEach((it, idx) => advance(it.id, idx * 250));
  };

  // Live path: upload the real files, then poll each review to completion.
  const intakeLive = async (files) => {
    const rows = files.map((f) => ({ id: newId(), file: f.name, stage: 1 }));
    setItems((x) => [...rows, ...x]);
    try {
      const submitted = await apiUpload(files); // returns in file order
      await Promise.all(submitted.map(async (s, i) => {
        const rowId = rows[i].id;
        const result = await apiPoll(s.id);
        setItems((x) => x.map((it) => (it.id === rowId ? { ...it, stage: STAGES.length - 1, live: result } : it)));
        if (result) onDone([adaptResult(result, s.file)]);
      }));
    } catch (e) {
      setItems((x) => x.map((it) => (rows.some((r) => r.id === it.id) ? { ...it, stage: STAGES.length - 1, error: true } : it)));
    }
  };

  const advance = (id, delay) => {
    let stage = 0;
    const step = () => {
      stage += 1;
      setItems((x) => x.map((it) => (it.id === id ? { ...it, stage } : it)));
      if (stage < STAGES.length - 1) setTimeout(step, 650);
      else {
        const done = itemsRef.current.find((it) => it.id === id);
        if (done) onDone([makeReview(done.file, done.key)]);
      }
    };
    setTimeout(step, delay + 400);
  };

  const onDrop = (e) => { e.preventDefault(); setDrag(false); intake(e.dataTransfer.files); };
  const doneCount = items.filter((i) => i.stage >= STAGES.length - 1).length;

  return (
    <div style={{ maxWidth: 820, margin: "0 auto", padding: "32px 24px" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em" }}>Upload creatives</h1>
      <p style={{ fontSize: 13, color: "#94a3b8", marginTop: 4 }}>
        Drop a whole campaign of creator videos at once. Each is reviewed independently and streamed into the queue as it is decided.
      </p>

      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className="rounded-xl flex flex-col items-center justify-center cursor-pointer"
        style={{
          marginTop: 22, padding: "44px 0",
          border: `1.5px dashed ${drag ? "#34d399" : "#243049"}`,
          background: drag ? "rgba(52,211,153,0.06)" : "#0b1220",
        }}>
        <UploadCloud size={30} color={drag ? "#34d399" : "#64748b"} />
        <div style={{ fontSize: 14, fontWeight: 500, marginTop: 12 }}>Drop video files here, or click to browse</div>
        <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>MP4, MOV, WebM &middot; bulk selection supported</div>
        <input ref={inputRef} type="file" accept="video/*" multiple style={{ display: "none" }}
          onChange={(e) => intake(e.target.files)} />
      </div>

      {items.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: "#64748b" }}>{doneCount} of {items.length} decided</div>
            {doneCount > 0 && (
              <button onClick={goQueue} className="flex items-center gap-1.5 rounded-lg"
                style={{ background: "#1e293b", color: "#e2e8f0", fontSize: 12.5, fontWeight: 500, padding: "7px 12px" }}>
                View in queue <ChevronRight size={14} />
              </button>
            )}
          </div>
          <div className="rounded-xl" style={{ border: "1px solid #1e293b", overflow: "hidden" }}>
            {items.map((it) => <UploadRow key={it.id} it={it} />)}
          </div>
        </div>
      )}
    </div>
  );
}

function UploadRow({ it }) {
  const done = it.stage >= STAGES.length - 1;
  const verdict = it.live ? it.live.decision : it.key ? TEMPLATES[it.key].verdict : null;
  const v = done && verdict ? VERDICT[verdict] : null;
  return (
    <div className="flex items-center gap-3" style={{ padding: "11px 14px", borderTop: "1px solid #14203a", background: "#0b1220" }}>
      <Film size={16} color="#475569" style={{ flexShrink: 0 }} />
      <div className="truncate" style={{ flex: 1, fontSize: 12.5 }}>{it.file}</div>
      {!done && (
        <div className="flex items-center gap-2" style={{ fontSize: 11.5, color: "#94a3b8" }}>
          <Loader2 size={13} className="animate-spin" /> {STAGES[it.stage]}
        </div>
      )}
      {done && it.error && <span style={{ fontSize: 11, color: "#fb7185" }}>Failed</span>}
      {done && v && (
        <span style={{ fontSize: 10.5, fontWeight: 700, color: v.color, background: v.soft, padding: "3px 9px", borderRadius: 5 }}>
          {v.label}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- Queue
function QueueView({ reviews, onOpen, goUpload, showToast }) {
  const [filter, setFilter] = useState("ALL");
  const [q, setQ] = useState("");
  const [sortDesc, setSortDesc] = useState(true);

  const counts = useMemo(() => reviews.reduce((a, r) => { a[r.verdict] = (a[r.verdict] || 0) + 1; return a; }, {}), [reviews]);
  const rows = useMemo(() => {
    let list = reviews.filter((r) => (filter === "ALL" || r.verdict === filter));
    if (q) list = list.filter((r) => (r.creator + r.file).toLowerCase().includes(q.toLowerCase()));
    const rank = { BLOCK: 0, REVIEW: 1, APPROVE: 2 };
    list = [...list].sort((a, b) => (sortDesc ? rank[a.verdict] - rank[b.verdict] : rank[b.verdict] - rank[a.verdict]));
    return list;
  }, [reviews, filter, q, sortDesc]);

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "28px 24px" }}>
      <div className="flex items-center justify-between">
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600 }}>Review queue</h1>
          <p style={{ fontSize: 13, color: "#94a3b8", marginTop: 4 }}>{reviews.length} creatives, auto-triaged. Open any to inspect the evidence.</p>
        </div>
        <button onClick={goUpload} className="flex items-center gap-1.5 rounded-lg"
          style={{ background: "linear-gradient(135deg,#34d399,#22d3ee)", color: "#020617", fontSize: 13, fontWeight: 600, padding: "9px 14px" }}>
          <UploadCloud size={15} /> Upload
        </button>
      </div>

      <div className="grid grid-cols-3 gap-3" style={{ marginTop: 20 }}>
        <SummaryCard label="Approved" n={counts.APPROVE || 0} c={VERDICT.APPROVE} sub="cleared to run" />
        <SummaryCard label="In review" n={counts.REVIEW || 0} c={VERDICT.REVIEW} sub="awaiting a human" />
        <SummaryCard label="Blocked" n={counts.BLOCK || 0} c={VERDICT.BLOCK} sub="not eligible" />
      </div>

      <div className="flex items-center gap-2" style={{ margin: "20px 0 10px" }}>
        {["ALL", "BLOCK", "REVIEW", "APPROVE"].map((f) => (
          <button key={f} onClick={() => setFilter(f)} className="rounded-lg" style={{
            fontSize: 12, fontWeight: 500, padding: "6px 12px",
            background: filter === f ? "#1e293b" : "transparent",
            color: filter === f ? "#e2e8f0" : "#64748b", border: "1px solid #1e293b",
          }}>{f === "ALL" ? "All" : VERDICT[f].label}</button>
        ))}
        <div className="flex items-center gap-2 rounded-lg" style={{ marginLeft: "auto", background: "#0b1220", border: "1px solid #1e293b", padding: "6px 10px" }}>
          <Search size={14} color="#64748b" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search creator or file"
            style={{ background: "transparent", border: "none", outline: "none", color: "#e2e8f0", fontSize: 12.5, width: 180 }} />
        </div>
        <button onClick={() => showToast("Exported queue to CSV")} className="flex items-center gap-1.5 rounded-lg"
          style={{ background: "#0b1220", border: "1px solid #1e293b", color: "#94a3b8", fontSize: 12, padding: "6px 11px" }}>
          <Download size={13} /> Export
        </button>
      </div>

      <div className="rounded-xl" style={{ border: "1px solid #1e293b", overflow: "hidden" }}>
        <div className="grid items-center" style={{ gridTemplateColumns: "1.4fr 1fr 0.9fr 2fr 70px", padding: "9px 14px", background: "#0b1220", fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em" }}>
          <span>Creator</span><span>File</span>
          <button onClick={() => setSortDesc((s) => !s)} className="flex items-center gap-1" style={{ color: "#64748b" }}>Verdict <ArrowUpDown size={11} /></button>
          <span>Top reason</span><span></span>
        </div>
        {rows.map((r) => {
          const cfg = VERDICT[r.verdict];
          return (
            <button key={r.id} onClick={() => onOpen(r.id)} className="w-full text-left grid items-center"
              style={{ gridTemplateColumns: "1.4fr 1fr 0.9fr 2fr 70px", padding: "11px 14px", borderTop: "1px solid #14203a", background: "#080e1c" }}>
              <div className="flex items-center gap-2.5" style={{ minWidth: 0 }}>
                <div className="rounded" style={{ width: 34, height: 24, flexShrink: 0, background: `hsl(${r.hue} 45% 22%)` }} />
                <span className="truncate" style={{ fontSize: 12.5, fontWeight: 500 }}>{r.creator}</span>
              </div>
              <span className="truncate" style={{ fontSize: 11.5, color: "#64748b" }}>{r.file}</span>
              <span><span style={{ fontSize: 10.5, fontWeight: 700, color: cfg.color, background: cfg.soft, padding: "3px 9px", borderRadius: 5 }}>{cfg.label}</span></span>
              <span className="truncate" style={{ fontSize: 11.5, color: "#94a3b8", paddingRight: 10 }}>{r.reasons[0]}</span>
              <span style={{ justifySelf: "end" }}><ChevronRight size={16} color="#475569" /></span>
            </button>
          );
        })}
        {rows.length === 0 && <div style={{ padding: "28px", textAlign: "center", fontSize: 13, color: "#475569" }}>No creatives match this filter.</div>}
      </div>
    </div>
  );
}

function SummaryCard({ label, n, c, sub }) {
  return (
    <div className="rounded-xl" style={{ background: "#0b1220", border: "1px solid #1e293b", padding: "16px 18px" }}>
      <div className="flex items-center gap-2"><span style={{ width: 8, height: 8, borderRadius: 99, background: c.color }} /><span style={{ fontSize: 12.5, color: "#94a3b8" }}>{label}</span></div>
      <div style={{ fontSize: 28, fontWeight: 700, marginTop: 6, color: c.color }}>{n}</div>
      <div style={{ fontSize: 11, color: "#64748b" }}>{sub}</div>
    </div>
  );
}

// --------------------------------------------------------------------- Detail
function DetailView({ review, back, showToast }) {
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [activeEv, setActiveEv] = useState(null);
  const timer = useRef(null);
  if (!review) return null;
  const v = review;

  const markers = v.policies.filter((p) => p.status === "flagged")
    .flatMap((p) => p.evidence.map((e) => ({ ...e, policy: p.label, contribution: p.contribution })));

  useEffect(() => {
    if (playing) timer.current = setInterval(() => setTime((t) => (t >= v.duration ? (setPlaying(false), v.duration) : +(t + 0.2).toFixed(1))), 90);
    return () => clearInterval(timer.current);
  }, [playing, v.duration]);

  const seek = (t, k = null) => { setTime(t); setActiveEv(k); };
  const live = markers.find((m) => time >= m.start && time <= m.end);
  const cfg = VERDICT[v.verdict];

  return (
    <div style={{ maxWidth: 1180, margin: "0 auto", padding: "20px 24px" }}>
      <button onClick={back} className="flex items-center gap-1.5" style={{ fontSize: 12.5, color: "#94a3b8", marginBottom: 14 }}>
        <ChevronLeft size={15} /> Back to queue
      </button>
      <div className="flex gap-5" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="rounded-xl overflow-hidden" style={{ border: "1px solid #1e293b" }}>
            <div className="relative flex items-center justify-center" style={{ height: 300, background: `radial-gradient(120% 120% at 50% 30%, hsl(${v.hue} 40% 26%), #0b1220 70%)` }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 12, color: "#cbd5e1" }}>{v.creator}</div>
                <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>preview frame &middot; {fmt(time)}</div>
              </div>
              {live && (
                <div className="absolute left-1/2" style={{ bottom: 16, transform: "translateX(-50%)", background: VERDICT[live.contribution].color, color: "#020617", fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 7, whiteSpace: "nowrap" }}>
                  {live.policy}: {live.label}
                </div>
              )}
            </div>
            <div style={{ background: "#0b1220", padding: "12px 16px" }}>
              <div className="flex items-center gap-3">
                <button onClick={() => setPlaying((p) => !p)} className="flex items-center justify-center rounded-full" style={{ width: 32, height: 32, background: "#1e293b", flexShrink: 0 }}>
                  {playing ? <Pause size={14} color="#e2e8f0" /> : <Play size={14} color="#e2e8f0" style={{ marginLeft: 2 }} />}
                </button>
                <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 12, color: "#94a3b8", width: 84 }}>{fmt(time)} / {fmt(v.duration)}</span>
                <div className="relative flex-1 rounded cursor-pointer" style={{ height: 32, background: "#111a2e", border: "1px solid #1e293b" }}
                  onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek(+(((e.clientX - r.left) / r.width) * v.duration).toFixed(1)); }}>
                  {markers.map((m, i) => {
                    const c = VERDICT[m.contribution], key = `${m.policy}-${i}`;
                    return <div key={key} title={m.label} onClick={(e) => { e.stopPropagation(); seek(m.start, key); }} className="absolute top-0 bottom-0"
                      style={{ left: `${(m.start / v.duration) * 100}%`, width: `${Math.max(2.5, ((m.end - m.start) / v.duration) * 100)}%`, background: c.color, opacity: activeEv === key || (time >= m.start && time <= m.end) ? 0.95 : 0.55, borderRadius: 3, boxShadow: activeEv === key ? `0 0 0 2px ${c.color}` : "none" }} />;
                  })}
                  <div className="absolute top-0 bottom-0" style={{ left: `${(time / v.duration) * 100}%`, width: 2, background: "#e2e8f0" }} />
                </div>
              </div>
              {markers.length === 0 && <div style={{ fontSize: 11, color: "#475569", marginTop: 8, paddingLeft: 47 }}>{v.offBriefGate ? "Stopped at the relevance gate. No compliance probes were run." : "No flagged moments. Clean across the full timeline."}</div>}
            </div>
          </div>
          <div className="rounded-xl mt-4" style={{ border: "1px solid #1e293b", background: "#0b1220", padding: 16 }}>
            <div className="flex items-center gap-2" style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}><Sparkles size={13} /> Auto-generated description</div>
            <p style={{ fontSize: 13.5, lineHeight: 1.65, color: "#cbd5e1" }}>{v.description}</p>
          </div>
        </div>

        <aside style={{ width: 360, flexShrink: 0 }}>
          <div className="rounded-xl" style={{ border: "1px solid #1e293b", background: "#0b1220" }}>
            <div style={{ padding: 18, borderBottom: "1px solid #1e293b" }}>
              <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>Decision</div>
              <div className="flex items-center gap-3 rounded-xl" style={{ background: cfg.soft, padding: "14px 16px" }}>
                <cfg.Icon size={26} color={cfg.color} />
                <div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: cfg.color }}>{v.verdict}</div>
                  <div style={{ fontSize: 11.5, color: "#94a3b8" }}>{v.verdict === "APPROVE" ? "Cleared to run as a paid ad" : v.verdict === "REVIEW" ? "Held for human review" : "Not eligible to run"}</div>
                </div>
              </div>
            </div>
            <div style={{ padding: "0 18px 18px" }}>
              <div className="grid grid-cols-3 gap-2" style={{ marginBottom: 16, marginTop: 16 }}>
                <Stat label="Confidence" value={v.confidence} />
                <Stat label="Relevance" value={v.relevance.toFixed(2)} dim={!v.onBrief} />
                <Stat label="On-brief" value={v.onBrief ? "yes" : "no"} dim={!v.onBrief} />
              </div>
              <Label>Why this decision</Label>
              <ul style={{ marginBottom: 18 }}>
                {v.reasons.map((r, i) => <li key={i} className="flex gap-2" style={{ fontSize: 12.5, color: "#cbd5e1", lineHeight: 1.55, marginBottom: 7 }}><ChevronRight size={14} style={{ marginTop: 2, flexShrink: 0, color: cfg.color }} /><span>{r}</span></li>)}
              </ul>
              <Label>Policy checks</Label>
              <div style={{ marginBottom: 18 }}>{v.policies.map((p) => <PolicyRow key={p.id} p={p} activeEv={activeEv} onSeek={seek} />)}</div>
              <Label>{v.verdict === "REVIEW" ? "Reviewer action" : "Override"}</Label>
              <div className="flex gap-2" style={{ marginTop: 8 }}>
                <button onClick={() => showToast("Approved and queued to run")} className="flex-1 rounded-lg" style={{ background: VERDICT.APPROVE.soft, color: VERDICT.APPROVE.color, fontSize: 12.5, fontWeight: 600, padding: "9px 0" }}>Approve</button>
                <button onClick={() => showToast("Blocked. Creator notified with reasons")} className="flex-1 rounded-lg" style={{ background: VERDICT.BLOCK.soft, color: VERDICT.BLOCK.color, fontSize: 12.5, fontWeight: 600, padding: "9px 0" }}>Block</button>
              </div>
              {v.humanReview && <div className="flex items-center gap-2 rounded-lg" style={{ marginTop: 10, padding: "8px 10px", background: "rgba(251,191,36,0.08)", fontSize: 11.5, color: "#fbbf24" }}><UserCheck size={14} /> Routed to a human. The system did not auto-decide on uncertainty.</div>}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function PolicyRow({ p, activeEv, onSeek }) {
  if (p.status === "clean") return <div className="flex items-center gap-2" style={{ padding: "6px 0", fontSize: 12.5, color: "#64748b" }}><CheckCircle2 size={15} color="#334155" /><span>{p.label}</span></div>;
  if (p.status === "skipped") return <div className="flex items-center gap-2" style={{ padding: "6px 0", fontSize: 12.5, color: "#3f4a5e" }}><X size={15} color="#27313f" /><span>{p.label} <span style={{ fontSize: 10.5 }}>not run</span></span></div>;
  const cfg = VERDICT[p.contribution];
  return (
    <div style={{ padding: "8px 0", borderTop: "1px solid #14203a" }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2" style={{ fontSize: 12.5, fontWeight: 500 }}><AlertTriangle size={15} color={cfg.color} /><span>{p.label}</span></div>
        <span style={{ fontSize: 10, fontWeight: 700, color: cfg.color, background: cfg.soft, padding: "2px 7px", borderRadius: 5 }}>{p.severity}</span>
      </div>
      {p.evidence.map((e, i) => {
        const key = `${p.label}-${i}`, MIcon = MODALITY_ICON[e.modality] || Eye;
        return (
          <button key={key} onClick={() => onSeek(e.start, key)} className="w-full text-left flex items-start gap-2 rounded-md"
            style={{ marginTop: 6, padding: "7px 9px", background: activeEv === key ? cfg.soft : "#0e1729", border: `1px solid ${activeEv === key ? cfg.color : "#14203a"}` }}>
            <MIcon size={13} color={cfg.color} style={{ marginTop: 1, flexShrink: 0 }} />
            <span style={{ fontSize: 11.5, color: "#cbd5e1", lineHeight: 1.45 }}>
              <span style={{ fontFamily: "ui-monospace, monospace", color: cfg.color }}>{fmt(e.start)}</span> {e.label}<span style={{ color: "#64748b" }}> &middot; {e.confidence} confidence</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Stat({ label, value, dim }) {
  return <div className="rounded-lg" style={{ background: "#0e1729", border: "1px solid #14203a", padding: "8px 10px" }}>
    <div style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
    <div style={{ fontSize: 14, fontWeight: 600, marginTop: 2, color: dim ? "#fb7185" : "#e2e8f0" }}>{value}</div>
  </div>;
}
function Label({ children }) { return <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", margin: "14px 0 8px" }}>{children}</div>; }
function Tab({ active, onClick, icon: Icon, children }) {
  return <button onClick={onClick} className="flex items-center gap-1.5 rounded-lg" style={{ fontSize: 13, fontWeight: 500, padding: "7px 13px", background: active ? "#1e293b" : "transparent", color: active ? "#e2e8f0" : "#64748b" }}><Icon size={15} />{children}</button>;
}
