import React, { useState, useEffect, useRef } from "react";
import {
  ShieldCheck, AlertTriangle, XCircle, CheckCircle2, Play, Pause,
  Clock, Eye, Mic, Type, FileCheck, ChevronRight, Sparkles, UserCheck
} from "lucide-react";

// ---------------------------------------------------------------------------
// Clearframe: ad compliance reviewer surface.
// Master-detail layout. The signature element is the evidence timeline:
// violations glow at their exact timestamps and seek the frame on click.
// Data mirrors the backend pipeline fixtures so the UI and API stay in sync.
// ---------------------------------------------------------------------------

const VERDICT = {
  APPROVE: { color: "#34d399", soft: "rgba(52,211,153,0.12)", label: "Approve", Icon: CheckCircle2 },
  REVIEW:  { color: "#fbbf24", soft: "rgba(251,191,36,0.12)", label: "Review",  Icon: AlertTriangle },
  BLOCK:   { color: "#fb7185", soft: "rgba(251,113,133,0.12)", label: "Block",   Icon: XCircle },
};

const MODALITY_ICON = { visual: Eye, audio: Mic, text: Type };

const SCENARIOS = [
  {
    id: "clean_tutorial",
    file: "clean_tutorial.mp4",
    creator: "@maya.beauty",
    campaign: "Lumiere Velvet Matte",
    duration: 75,
    verdict: "APPROVE",
    confidence: "high",
    relevance: 0.88,
    onBrief: true,
    humanReview: false,
    hue: 168,
    description:
      "A creator demonstrates a matte lipstick and foundation from the Lumiere Velvet Matte collection, applying each evenly to the face while narrating the steps and showing the packaging to camera. The focus stays on the product throughout.",
    reasons: ["No policy violations detected. On-brief and clean across all categories."],
    policies: [
      { id: "hate_harassment", label: "Hate / harassment", status: "clean" },
      { id: "drugs_illegal", label: "Drugs / illegal behaviour", status: "clean" },
      { id: "profanity", label: "Profanity", status: "clean" },
      { id: "unsafe_usage", label: "Unsafe product usage", status: "clean" },
      { id: "medical_claims", label: "Medical / cosmetic claims", status: "clean" },
    ],
  },
  {
    id: "eye_misuse_claim",
    file: "eye_misuse_claim.mp4",
    creator: "@priya.glow",
    campaign: "Lumiere Velvet Matte",
    duration: 78,
    verdict: "BLOCK",
    confidence: "high",
    relevance: 0.82,
    onBrief: true,
    humanReview: false,
    hue: 350,
    description:
      "A creator demonstrates an eyeliner and a serum. Partway through she applies product directly onto the inner waterline in a way that touches the eyeball, then states the serum cures acne and treats rosacea within a week. The remainder is a standard get ready with me routine.",
    reasons: [
      "Unsafe product usage at high severity, corroborated by a timestamped clip.",
      "Medical claim at high severity: a cosmetic cannot claim to cure acne or treat rosacea.",
    ],
    policies: [
      { id: "hate_harassment", label: "Hate / harassment", status: "clean" },
      { id: "drugs_illegal", label: "Drugs / illegal behaviour", status: "clean" },
      { id: "profanity", label: "Profanity", status: "clean" },
      {
        id: "unsafe_usage", label: "Unsafe product usage", status: "flagged",
        severity: "high", contribution: "BLOCK",
        evidence: [{ start: 34, end: 42, confidence: "high", modality: "visual",
          label: "Product applied onto the eyeball and inner waterline" }],
      },
      {
        id: "medical_claims", label: "Medical / cosmetic claims", status: "flagged",
        severity: "high", contribution: "BLOCK",
        evidence: [{ start: 57, end: 61, confidence: "high", modality: "audio",
          label: "Claims the serum cures acne and treats rosacea" }],
      },
    ],
  },
  {
    id: "mild_profanity",
    file: "mild_profanity.mp4",
    creator: "@jordan.grwm",
    campaign: "Lumiere Velvet Matte",
    duration: 70,
    verdict: "REVIEW",
    confidence: "high",
    relevance: 0.86,
    onBrief: true,
    humanReview: true,
    hue: 41,
    description:
      "A creator films a get ready with me routine using the matte foundation and lipstick, shown and applied clearly on the face. At one point she uses a single mild swear word reacting to a smudge, then continues the tutorial normally.",
    reasons: [
      "Profanity at low severity: below the block threshold, above the review threshold.",
      "Limited profanity tolerance for this advertiser routes a single instance to a human.",
    ],
    policies: [
      { id: "hate_harassment", label: "Hate / harassment", status: "clean" },
      { id: "drugs_illegal", label: "Drugs / illegal behaviour", status: "clean" },
      {
        id: "profanity", label: "Profanity", status: "flagged",
        severity: "low", contribution: "REVIEW",
        evidence: [{ start: 46.5, end: 48, confidence: "medium", modality: "audio",
          label: "A single mild swear word in reaction to a smudge" }],
      },
      { id: "unsafe_usage", label: "Unsafe product usage", status: "clean" },
      { id: "medical_claims", label: "Medical / cosmetic claims", status: "clean" },
    ],
  },
  {
    id: "offbrief_clickbait",
    file: "offbrief_clickbait.mp4",
    creator: "@dailyvibes",
    campaign: "Lumiere Velvet Matte",
    duration: 64,
    verdict: "BLOCK",
    confidence: "high",
    relevance: 0.28,
    onBrief: false,
    humanReview: false,
    hue: 280,
    offBriefGate: true,
    description:
      "A fast-paced lifestyle vlog of the creator running errands, getting coffee and filming a short dance. A makeup product appears briefly on a table in the background but is never picked up, named or applied. Most of the runtime is unrelated to cosmetics.",
    reasons: [
      "Off-brief: relevance 0.28 is below the 0.55 threshold and the model judged it off-brief.",
      "Rejected at the relevance gate before deep compliance analysis ran.",
    ],
    policies: [
      { id: "hate_harassment", label: "Hate / harassment", status: "skipped" },
      { id: "drugs_illegal", label: "Drugs / illegal behaviour", status: "skipped" },
      { id: "profanity", label: "Profanity", status: "skipped" },
      { id: "unsafe_usage", label: "Unsafe product usage", status: "skipped" },
      { id: "medical_claims", label: "Medical / cosmetic claims", status: "skipped" },
    ],
  },
];

const fmt = (s) => {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, "0")}`;
};

export default function Clearframe() {
  const [selectedId, setSelectedId] = useState("eye_misuse_claim");
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [activeEv, setActiveEv] = useState(null);
  const [toast, setToast] = useState(null);
  const timer = useRef(null);

  const v = SCENARIOS.find((s) => s.id === selectedId);
  const markers = v.policies
    .filter((p) => p.status === "flagged")
    .flatMap((p) => p.evidence.map((e) => ({ ...e, policy: p.label, contribution: p.contribution })));

  // playback
  useEffect(() => {
    if (playing) {
      timer.current = setInterval(() => {
        setTime((t) => {
          if (t >= v.duration) { setPlaying(false); return v.duration; }
          return +(t + 0.2).toFixed(1);
        });
      }, 90);
    }
    return () => clearInterval(timer.current);
  }, [playing, v.duration]);

  // reset on scenario change
  useEffect(() => { setTime(0); setPlaying(false); setActiveEv(null); }, [selectedId]);

  const seek = (t, evKey = null) => { setTime(t); setActiveEv(evKey); };
  const liveMarker = markers.find((m) => time >= m.start && time <= m.end);

  const counts = SCENARIOS.reduce((a, s) => { a[s.verdict]++; return a; }, { APPROVE: 0, REVIEW: 0, BLOCK: 0 });
  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 2600); };

  return (
    <div style={{ background: "#020617", color: "#e2e8f0", minHeight: "100vh", fontFamily: "ui-sans-serif, system-ui, -apple-system, sans-serif" }}>
      {/* Header */}
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
        <div className="flex items-center gap-4" style={{ fontSize: 12 }}>
          <span style={{ color: "#64748b" }}>Lumiere Cosmetics &middot; Spring 2026</span>
          <Pill n={counts.APPROVE} c={VERDICT.APPROVE.color} label="approve" />
          <Pill n={counts.REVIEW} c={VERDICT.REVIEW.color} label="review" />
          <Pill n={counts.BLOCK} c={VERDICT.BLOCK.color} label="block" />
        </div>
      </header>

      <div className="flex" style={{ height: "calc(100vh - 58px)" }}>
        {/* Queue rail */}
        <aside className="border-r overflow-y-auto" style={{ width: 280, borderColor: "#1e293b", background: "#0b1220" }}>
          <div className="px-4 py-3" style={{ fontSize: 11, letterSpacing: "0.08em", color: "#64748b", textTransform: "uppercase" }}>
            Review queue
          </div>
          {SCENARIOS.map((s) => {
            const cfg = VERDICT[s.verdict];
            const active = s.id === selectedId;
            return (
              <button key={s.id} onClick={() => setSelectedId(s.id)}
                className="w-full text-left px-4 py-3 flex items-center gap-3 border-l-2"
                style={{
                  background: active ? "#111a2e" : "transparent",
                  borderColor: active ? cfg.color : "transparent",
                }}>
                <div className="rounded" style={{ width: 44, height: 30, flexShrink: 0, background: `hsl(${s.hue} 45% 22%)` }} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="truncate" style={{ fontSize: 12.5, fontWeight: 500 }}>{s.creator}</div>
                  <div className="truncate" style={{ fontSize: 11, color: "#64748b" }}>{s.file}</div>
                </div>
                <span style={{ fontSize: 10, fontWeight: 700, color: cfg.color, background: cfg.soft, padding: "2px 7px", borderRadius: 5 }}>
                  {cfg.label}
                </span>
              </button>
            );
          })}
          <div className="px-4 py-3 mt-2" style={{ fontSize: 11, color: "#475569", lineHeight: 1.6 }}>
            Auto-triaged. Items needing a human are tagged Review. Everything else is decided automatically.
          </div>
        </aside>

        {/* Center stage */}
        <main className="flex-1 overflow-y-auto" style={{ padding: 24 }}>
          {/* Video frame */}
          <div className="rounded-xl overflow-hidden relative" style={{ border: "1px solid #1e293b" }}>
            <div className="relative flex items-center justify-center"
              style={{ height: 320, background: `radial-gradient(120% 120% at 50% 30%, hsl(${v.hue} 40% 26%), #0b1220 70%)` }}>
              <div style={{ textAlign: "center", opacity: 0.85 }}>
                <div style={{ fontSize: 12, color: "#cbd5e1", letterSpacing: "0.05em" }}>{v.creator}</div>
                <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>preview frame &middot; {fmt(time)}</div>
              </div>
              {/* live violation caption */}
              {liveMarker && (
                <div className="absolute left-1/2" style={{
                  bottom: 18, transform: "translateX(-50%)",
                  background: VERDICT[liveMarker.contribution].color, color: "#020617",
                  fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 7, whiteSpace: "nowrap",
                  boxShadow: "0 4px 18px rgba(0,0,0,0.4)",
                }}>
                  {liveMarker.policy}: {liveMarker.label}
                </div>
              )}
            </div>

            {/* Transport + timeline */}
            <div style={{ background: "#0b1220", padding: "12px 16px" }}>
              <div className="flex items-center gap-3">
                <button onClick={() => setPlaying((p) => !p)}
                  className="flex items-center justify-center rounded-full"
                  style={{ width: 34, height: 34, background: "#1e293b", flexShrink: 0 }}>
                  {playing ? <Pause size={15} color="#e2e8f0" /> : <Play size={15} color="#e2e8f0" style={{ marginLeft: 2 }} />}
                </button>
                <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 12, color: "#94a3b8", width: 84 }}>
                  {fmt(time)} / {fmt(v.duration)}
                </span>

                {/* timeline track */}
                <div className="relative flex-1 rounded cursor-pointer"
                  style={{ height: 34, background: "#111a2e", border: "1px solid #1e293b" }}
                  onClick={(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    seek(+(((e.clientX - r.left) / r.width) * v.duration).toFixed(1));
                  }}>
                  {/* evidence markers */}
                  {markers.map((m, i) => {
                    const cfg = VERDICT[m.contribution];
                    const key = `${m.policy}-${i}`;
                    return (
                      <div key={key} title={m.label}
                        onClick={(ev) => { ev.stopPropagation(); seek(m.start, key); }}
                        className="absolute top-0 bottom-0"
                        style={{
                          left: `${(m.start / v.duration) * 100}%`,
                          width: `${Math.max(2.5, ((m.end - m.start) / v.duration) * 100)}%`,
                          background: cfg.color,
                          opacity: activeEv === key || (time >= m.start && time <= m.end) ? 0.95 : 0.55,
                          borderRadius: 3,
                          boxShadow: activeEv === key ? `0 0 0 2px ${cfg.color}` : "none",
                        }} />
                    );
                  })}
                  {/* playhead */}
                  <div className="absolute top-0 bottom-0" style={{ left: `${(time / v.duration) * 100}%`, width: 2, background: "#e2e8f0" }} />
                </div>
              </div>
              {markers.length === 0 && (
                <div style={{ fontSize: 11, color: "#475569", marginTop: 8, paddingLeft: 49 }}>
                  {v.offBriefGate ? "Stopped at the relevance gate. No compliance probes were run." : "No flagged moments. Clean across the full timeline."}
                </div>
              )}
            </div>
          </div>

          {/* Auto description */}
          <div className="rounded-xl mt-4" style={{ border: "1px solid #1e293b", background: "#0b1220", padding: 16 }}>
            <div className="flex items-center gap-2" style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
              <Sparkles size={13} /> Auto-generated description
            </div>
            <p style={{ fontSize: 13.5, lineHeight: 1.65, color: "#cbd5e1" }}>{v.description}</p>
          </div>
        </main>

        {/* Decision panel */}
        <aside className="border-l overflow-y-auto" style={{ width: 360, borderColor: "#1e293b", background: "#0b1220" }}>
          <DecisionHeader v={v} />

          <div style={{ padding: "0 18px 18px" }}>
            {/* signal row */}
            <div className="grid grid-cols-3 gap-2" style={{ marginBottom: 16 }}>
              <Stat label="Confidence" value={v.confidence} />
              <Stat label="Relevance" value={v.relevance.toFixed(2)} dim={!v.onBrief} />
              <Stat label="On-brief" value={v.onBrief ? "yes" : "no"} dim={!v.onBrief} />
            </div>

            {/* reasons */}
            <SectionLabel>Why this decision</SectionLabel>
            <ul style={{ marginBottom: 18 }}>
              {v.reasons.map((r, i) => (
                <li key={i} className="flex gap-2" style={{ fontSize: 12.5, color: "#cbd5e1", lineHeight: 1.55, marginBottom: 7 }}>
                  <ChevronRight size={14} style={{ marginTop: 2, flexShrink: 0, color: VERDICT[v.verdict].color }} />
                  <span>{r}</span>
                </li>
              ))}
            </ul>

            {/* policy checklist */}
            <SectionLabel>Policy checks</SectionLabel>
            <div style={{ marginBottom: 18 }}>
              {v.policies.map((p) => (
                <PolicyRow key={p.id} p={p} activeEv={activeEv} onSeek={seek} />
              ))}
            </div>

            {/* HITL actions */}
            <SectionLabel>{v.verdict === "REVIEW" ? "Reviewer action" : "Override"}</SectionLabel>
            <div className="flex gap-2" style={{ marginTop: 8 }}>
              <button onClick={() => showToast("Approved and queued to run")}
                className="flex-1 rounded-lg" style={{ background: VERDICT.APPROVE.soft, color: VERDICT.APPROVE.color, fontSize: 12.5, fontWeight: 600, padding: "9px 0" }}>
                Approve
              </button>
              <button onClick={() => showToast("Blocked. Creator notified with reasons")}
                className="flex-1 rounded-lg" style={{ background: VERDICT.BLOCK.soft, color: VERDICT.BLOCK.color, fontSize: 12.5, fontWeight: 600, padding: "9px 0" }}>
                Block
              </button>
            </div>
            {v.humanReview && (
              <div className="flex items-center gap-2 rounded-lg" style={{ marginTop: 10, padding: "8px 10px", background: "rgba(251,191,36,0.08)", fontSize: 11.5, color: "#fbbf24" }}>
                <UserCheck size={14} /> Routed to a human. The system did not auto-decide on uncertainty.
              </div>
            )}
          </div>
        </aside>
      </div>

      {toast && (
        <div className="fixed left-1/2" style={{ bottom: 24, transform: "translateX(-50%)", background: "#1e293b", color: "#e2e8f0", fontSize: 13, padding: "10px 16px", borderRadius: 9, boxShadow: "0 8px 30px rgba(0,0,0,0.5)" }}>
          {toast}
        </div>
      )}
    </div>
  );
}

function DecisionHeader({ v }) {
  const cfg = VERDICT[v.verdict];
  return (
    <div style={{ padding: 18, borderBottom: "1px solid #1e293b" }}>
      <div className="flex items-center gap-2" style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
        Decision
      </div>
      <div className="flex items-center gap-3 rounded-xl" style={{ background: cfg.soft, padding: "14px 16px" }}>
        <cfg.Icon size={26} color={cfg.color} />
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: cfg.color, letterSpacing: "-0.01em" }}>{v.verdict}</div>
          <div style={{ fontSize: 11.5, color: "#94a3b8" }}>
            {v.verdict === "APPROVE" ? "Cleared to run as a paid ad" : v.verdict === "REVIEW" ? "Held for human review" : "Not eligible to run"}
          </div>
        </div>
      </div>
    </div>
  );
}

function PolicyRow({ p, activeEv, onSeek }) {
  if (p.status === "clean") {
    return (
      <div className="flex items-center gap-2" style={{ padding: "6px 0", fontSize: 12.5, color: "#64748b" }}>
        <CheckCircle2 size={15} color="#334155" /> <span>{p.label}</span>
      </div>
    );
  }
  if (p.status === "skipped") {
    return (
      <div className="flex items-center gap-2" style={{ padding: "6px 0", fontSize: 12.5, color: "#3f4a5e" }}>
        <Clock size={15} color="#27313f" /> <span>{p.label} <span style={{ fontSize: 10.5 }}>not run</span></span>
      </div>
    );
  }
  const cfg = VERDICT[p.contribution];
  return (
    <div style={{ padding: "8px 0", borderTop: "1px solid #14203a" }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2" style={{ fontSize: 12.5, fontWeight: 500 }}>
          <AlertTriangle size={15} color={cfg.color} /> <span>{p.label}</span>
        </div>
        <span style={{ fontSize: 10, fontWeight: 700, color: cfg.color, background: cfg.soft, padding: "2px 7px", borderRadius: 5 }}>
          {p.severity}
        </span>
      </div>
      {p.evidence.map((e, i) => {
        const key = `${p.label}-${i}`;
        const MIcon = MODALITY_ICON[e.modality] || Eye;
        return (
          <button key={key} onClick={() => onSeek(e.start, key)}
            className="w-full text-left flex items-start gap-2 rounded-md"
            style={{ marginTop: 6, padding: "7px 9px", background: activeEv === key ? cfg.soft : "#0e1729", border: `1px solid ${activeEv === key ? cfg.color : "#14203a"}` }}>
            <MIcon size={13} color={cfg.color} style={{ marginTop: 1, flexShrink: 0 }} />
            <span style={{ fontSize: 11.5, color: "#cbd5e1", lineHeight: 1.45 }}>
              <span style={{ fontFamily: "ui-monospace, monospace", color: cfg.color }}>{fmt(e.start)}</span> {e.label}
              <span style={{ color: "#64748b" }}> &middot; {e.confidence} confidence</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Stat({ label, value, dim }) {
  return (
    <div className="rounded-lg" style={{ background: "#0e1729", border: "1px solid #14203a", padding: "8px 10px" }}>
      <div style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 600, marginTop: 2, color: dim ? "#fb7185" : "#e2e8f0" }}>{value}</div>
    </div>
  );
}

function SectionLabel({ children }) {
  return <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.06em", margin: "14px 0 8px" }}>{children}</div>;
}

function Pill({ n, c, label }) {
  return (
    <span className="flex items-center gap-1.5">
      <span style={{ width: 7, height: 7, borderRadius: 99, background: c, display: "inline-block" }} />
      <span style={{ color: "#cbd5e1" }}>{n}</span>
      <span style={{ color: "#64748b" }}>{label}</span>
    </span>
  );
}
