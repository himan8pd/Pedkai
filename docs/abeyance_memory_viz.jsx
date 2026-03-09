import { useState, useEffect, useRef, useCallback } from "react";

const FRAGMENTS = [
  { id: "A", label: "Ticket: high BLER\ncell 8842-A", domain: "RAN", source: "ticket", week: 1, rawX: 120, rawY: 80, enrX: 280, enrY: 160, cluster: "NW-1847" },
  { id: "B", label: "Alarm: CRC errors\nS1 bearer ENB-4421", domain: "Transport", source: "alarm", week: 3, rawX: 380, rawY: 280, enrX: 320, enrY: 200, cluster: "NW-1847" },
  { id: "C", label: "Telemetry: pkt loss\nVLAN 342", domain: "IP", source: "telemetry", week: 5, rawX: 480, rawY: 120, enrX: 260, enrY: 240, cluster: "NW-1847" },
  { id: "D", label: "Change: FW upgrade\nTN-NW-207", domain: "Change", source: "change", week: 0, rawX: 200, rawY: 380, enrX: 340, enrY: 180, cluster: "NW-1847" },
  { id: "E", label: "Ticket: no fault found\nsite S-4221", domain: "RAN", source: "ticket", week: 2, rawX: 520, rawY: 400, enrX: 560, enrY: 340, cluster: "S-4221" },
  { id: "F", label: "Telemetry: zero-user\ncell 4221-B", domain: "RAN", source: "telemetry", week: 4, rawX: 100, rawY: 420, enrX: 600, enrY: 300, cluster: "S-4221" },
  { id: "G", label: "Alarm: self-cleared\nRF power alarm", domain: "RAN", source: "alarm", week: 6, rawX: 440, rawY: 50, enrX: 580, enrY: 380, cluster: "S-4221" },
  { id: "H", label: "Ticket: timeout\nCR-EAST-17", domain: "Core", source: "ticket", week: 7, rawX: 300, rawY: 450, enrX: 140, enrY: 420, cluster: "alone" },
];

const EDGES = [
  { from: "A", to: "B", score: 0.50, week: 3 },
  { from: "A", to: "D", score: 0.42, week: 5 },
  { from: "B", to: "D", score: 0.48, week: 5 },
  { from: "B", to: "C", score: 0.45, week: 5 },
  { from: "C", to: "D", score: 0.38, week: 5 },
  { from: "E", to: "F", score: 0.52, week: 4 },
  { from: "F", to: "G", score: 0.47, week: 6 },
  { from: "E", to: "G", score: 0.41, week: 6 },
];

const DOMAIN_COLORS = {
  RAN: "#ef4444",
  Transport: "#3b82f6",
  IP: "#8b5cf6",
  Change: "#f59e0b",
  Core: "#6b7280",
};

const SOURCE_SHAPES = {
  ticket: "circle",
  alarm: "square",
  telemetry: "diamond",
  change: "triangle",
};

const CLUSTER_COLORS = {
  "NW-1847": "rgba(59, 130, 246, 0.08)",
  "S-4221": "rgba(239, 68, 68, 0.08)",
  alone: "transparent",
};

const CLUSTER_BORDERS = {
  "NW-1847": "rgba(59, 130, 246, 0.3)",
  "S-4221": "rgba(239, 68, 68, 0.3)",
  alone: "transparent",
};

function Shape({ x, y, type, color, size = 16, opacity = 1, pulse = false, label, id }) {
  const s = size;
  return (
    <g opacity={opacity}>
      {pulse && (
        <circle cx={x} cy={y} r={s + 8} fill="none" stroke={color} strokeWidth={2} opacity={0.3}>
          <animate attributeName="r" from={s + 4} to={s + 16} dur="1.5s" repeatCount="indefinite" />
          <animate attributeName="opacity" from={0.4} to={0} dur="1.5s" repeatCount="indefinite" />
        </circle>
      )}
      {type === "circle" && <circle cx={x} cy={y} r={s} fill={color} stroke="#fff" strokeWidth={2} />}
      {type === "square" && <rect x={x - s} y={y - s} width={s * 2} height={s * 2} fill={color} stroke="#fff" strokeWidth={2} rx={3} />}
      {type === "diamond" && (
        <polygon points={`${x},${y - s * 1.2} ${x + s * 1.2},${y} ${x},${y + s * 1.2} ${x - s * 1.2},${y}`} fill={color} stroke="#fff" strokeWidth={2} />
      )}
      {type === "triangle" && (
        <polygon points={`${x},${y - s * 1.2} ${x + s * 1.1},${y + s * 0.8} ${x - s * 1.1},${y + s * 0.8}`} fill={color} stroke="#fff" strokeWidth={2} />
      )}
      <text x={x} y={y + s + 16} textAnchor="middle" fontSize={10} fill="#64748b" fontFamily="monospace">
        {id}
      </text>
      {label && label.split("\n").map((line, i) => (
        <text key={i} x={x} y={y - s - 12 + i * 12} textAnchor="middle" fontSize={9} fill="#334155" fontWeight={500}>
          {line}
        </text>
      ))}
    </g>
  );
}

function ClusterBubble({ fragments, label, view }) {
  if (!fragments.length) return null;
  const key = view === "raw" ? ["rawX", "rawY"] : ["enrX", "enrY"];
  const xs = fragments.map((f) => f[key[0]]);
  const ys = fragments.map((f) => f[key[1]]);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const rx = (Math.max(...xs) - Math.min(...xs)) / 2 + 60;
  const ry = (Math.max(...ys) - Math.min(...ys)) / 2 + 55;
  const cluster = fragments[0].cluster;
  return (
    <g>
      <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill={CLUSTER_COLORS[cluster]} stroke={CLUSTER_BORDERS[cluster]} strokeWidth={2} strokeDasharray="6 4" />
      {view === "enriched" && (
        <text x={cx} y={cy - ry - 6} textAnchor="middle" fontSize={11} fill="#475569" fontWeight={600}>
          {label}
        </text>
      )}
    </g>
  );
}

function EdgeLine({ from, to, score, view, active, snap }) {
  const key = view === "raw" ? ["rawX", "rawY"] : ["enrX", "enrY"];
  const x1 = from[key[0]], y1 = from[key[1]];
  const x2 = to[key[0]], y2 = to[key[1]];
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  if (!active) return null;
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={snap ? "#22c55e" : "#94a3b8"} strokeWidth={snap ? 3 : 1.5} strokeDasharray={snap ? "none" : "4 3"} opacity={snap ? 0.9 : 0.5} />
      <rect x={mx - 16} y={my - 8} width={32} height={16} rx={4} fill={snap ? "#22c55e" : "#f1f5f9"} stroke={snap ? "#16a34a" : "#cbd5e1"} strokeWidth={1} />
      <text x={mx} y={my + 4} textAnchor="middle" fontSize={9} fill={snap ? "#fff" : "#64748b"} fontWeight={600}>
        {score.toFixed(2)}
      </text>
    </g>
  );
}

const TABS = [
  { key: "embedding", label: "Embedding Space" },
  { key: "snap", label: "Snap Timeline" },
  { key: "decay", label: "Decay Profiles" },
  { key: "value", label: "Value Attribution" },
  { key: "shadow", label: "Shadow Topology" },
];

export default function AbeyanceViz() {
  const [tab, setTab] = useState("embedding");
  const [embView, setEmbView] = useState("raw");
  const [snapWeek, setSnapWeek] = useState(0);
  const [showLabels, setShowLabels] = useState(true);
  const [animating, setAnimating] = useState(false);

  const runSnapAnimation = useCallback(() => {
    setAnimating(true);
    setSnapWeek(0);
    let w = 0;
    const iv = setInterval(() => {
      w++;
      setSnapWeek(w);
      if (w >= 8) { clearInterval(iv); setAnimating(false); }
    }, 1200);
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 p-4">
      <div className="max-w-5xl mx-auto">
        <div className="mb-4">
          <h1 className="text-2xl font-bold text-slate-800">Abeyance Memory</h1>
          <p className="text-sm text-slate-500 mt-1">Interactive architecture visualisation — PedkAI's core differentiator</p>
        </div>

        <div className="flex gap-1 mb-4 bg-white rounded-lg p-1 shadow-sm border border-slate-200">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-3 py-2 rounded-md text-xs font-medium transition-all ${tab === t.key ? "bg-slate-800 text-white shadow" : "text-slate-600 hover:bg-slate-100"}`}>
              {t.label}
            </button>
          ))}
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          {tab === "embedding" && <EmbeddingTab view={embView} setView={setEmbView} showLabels={showLabels} setShowLabels={setShowLabels} />}
          {tab === "snap" && <SnapTab week={snapWeek} setWeek={setSnapWeek} runAnimation={runSnapAnimation} animating={animating} />}
          {tab === "decay" && <DecayTab />}
          {tab === "value" && <ValueTab />}
          {tab === "shadow" && <ShadowTab />}
        </div>
      </div>
    </div>
  );
}

function EmbeddingTab({ view, setView, showLabels, setShowLabels }) {
  const nw = FRAGMENTS.filter((f) => f.cluster === "NW-1847");
  const s42 = FRAGMENTS.filter((f) => f.cluster === "S-4221");
  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Fragment Embedding Space</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {view === "raw" ? "Raw embeddings — fragments scatter by vocabulary, not by operational reality" : "Enriched embeddings — topology + temporal + operational context pulls related evidence together"}
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            <input type="checkbox" checked={showLabels} onChange={() => setShowLabels(!showLabels)} className="rounded" />
            Labels
          </label>
          <div className="flex bg-slate-100 rounded-lg p-0.5">
            <button onClick={() => setView("raw")} className={`px-3 py-1 rounded-md text-xs font-medium ${view === "raw" ? "bg-white shadow text-slate-800" : "text-slate-500"}`}>
              Raw
            </button>
            <button onClick={() => setView("enriched")} className={`px-3 py-1 rounded-md text-xs font-medium ${view === "enriched" ? "bg-white shadow text-slate-800" : "text-slate-500"}`}>
              Enriched
            </button>
          </div>
        </div>
      </div>
      <svg viewBox="0 0 720 500" className="w-full border border-slate-100 rounded-lg bg-slate-50/50">
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#e2e8f0" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="720" height="500" fill="url(#grid)" />
        {view === "enriched" && (
          <>
            <ClusterBubble fragments={nw} label="Cluster: Site NW-1847 corridor" view={view} />
            <ClusterBubble fragments={s42} label="Cluster: Site S-4221 area" view={view} />
          </>
        )}
        {view === "enriched" && EDGES.filter(e => ["NW-1847"].includes(FRAGMENTS.find(f=>f.id===e.from).cluster) && FRAGMENTS.find(f=>f.id===e.from).cluster === FRAGMENTS.find(f=>f.id===e.to).cluster).map((e, i) => {
          const from = FRAGMENTS.find((f) => f.id === e.from);
          const to = FRAGMENTS.find((f) => f.id === e.to);
          return <EdgeLine key={i} from={from} to={to} score={e.score} view={view} active={true} snap={false} />;
        })}
        {FRAGMENTS.map((f) => (
          <Shape key={f.id} x={view === "raw" ? f.rawX : f.enrX} y={view === "raw" ? f.rawY : f.enrY}
            type={SOURCE_SHAPES[f.source]} color={DOMAIN_COLORS[f.domain]}
            label={showLabels ? f.label : null} id={f.id} pulse={view === "enriched" && f.cluster === "alone"} />
        ))}
        {view === "enriched" && (
          <text x={140} y={455} textAnchor="middle" fontSize={10} fill="#94a3b8" fontStyle="italic">
            ↑ alone — waiting in abeyance
          </text>
        )}
      </svg>
      <div className="flex gap-4 mt-3 justify-center flex-wrap">
        {Object.entries(DOMAIN_COLORS).map(([d, c]) => (
          <div key={d} className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full" style={{ backgroundColor: c }} />
            <span className="text-xs text-slate-500">{d}</span>
          </div>
        ))}
        <span className="text-slate-300">|</span>
        <div className="flex items-center gap-1.5"><span className="text-xs">○ Ticket</span></div>
        <div className="flex items-center gap-1.5"><span className="text-xs">□ Alarm</span></div>
        <div className="flex items-center gap-1.5"><span className="text-xs">◇ Telemetry</span></div>
        <div className="flex items-center gap-1.5"><span className="text-xs">△ Change</span></div>
      </div>
    </div>
  );
}

function SnapTab({ week, setWeek, runAnimation, animating }) {
  const visible = FRAGMENTS.filter((f) => f.week <= week);
  const activeEdges = EDGES.filter((e) => e.week <= week);
  const snapped = week >= 8;
  const noisyOr = activeEdges.filter(e => FRAGMENTS.find(f=>f.id===e.from).cluster === "NW-1847" && FRAGMENTS.find(f=>f.id===e.to).cluster === "NW-1847")
    .reduce((acc, e) => acc * (1 - e.score), 1);
  const fusionScore = 1 - noisyOr;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Snap Timeline — Evidence Accumulation</h2>
          <p className="text-xs text-slate-500 mt-0.5">Watch fragments arrive over weeks and weak affinities accumulate into a cluster snap</p>
        </div>
        <div className="flex gap-2 items-center">
          <button onClick={runAnimation} disabled={animating}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium ${animating ? "bg-slate-200 text-slate-400" : "bg-slate-800 text-white hover:bg-slate-700"}`}>
            {animating ? "Playing..." : "▶ Play"}
          </button>
        </div>
      </div>
      <div className="flex gap-2 mb-3 items-center">
        <span className="text-xs text-slate-500 w-14">Week {week}</span>
        <input type="range" min={0} max={8} value={week} onChange={(e) => setWeek(Number(e.target.value))}
          className="flex-1 h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-slate-800" />
      </div>
      <svg viewBox="0 0 720 500" className="w-full border border-slate-100 rounded-lg bg-slate-50/50">
        <defs>
          <pattern id="grid2" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#e2e8f0" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="720" height="500" fill="url(#grid2)" />
        {snapped && (
          <ellipse cx={300} cy={195} rx={120} ry={90} fill="rgba(34,197,94,0.06)" stroke="rgba(34,197,94,0.4)" strokeWidth={3} strokeDasharray="none">
            <animate attributeName="stroke-opacity" values="0.2;0.6;0.2" dur="2s" repeatCount="indefinite" />
          </ellipse>
        )}
        {activeEdges.map((e, i) => {
          const from = FRAGMENTS.find((f) => f.id === e.from);
          const to = FRAGMENTS.find((f) => f.id === e.to);
          if (!visible.includes(from) || !visible.includes(to)) return null;
          return <EdgeLine key={i} from={from} to={to} score={e.score} view="enriched" active={true} snap={snapped && from.cluster === "NW-1847" && to.cluster === "NW-1847"} />;
        })}
        {visible.map((f) => (
          <Shape key={f.id} x={f.enrX} y={f.enrY} type={SOURCE_SHAPES[f.source]} color={DOMAIN_COLORS[f.domain]}
            label={f.label} id={f.id} pulse={f.week === week} />
        ))}
        {snapped && (
          <g>
            <rect x={440} y={30} width={260} height={110} rx={8} fill="#f0fdf4" stroke="#22c55e" strokeWidth={2} />
            <text x={570} y={55} textAnchor="middle" fontSize={13} fill="#16a34a" fontWeight={700}>CLUSTER SNAP!</text>
            <text x={570} y={75} textAnchor="middle" fontSize={10} fill="#15803d">Noisy-OR Fusion: {fusionScore.toFixed(3)}</text>
            <text x={570} y={95} textAnchor="middle" fontSize={10} fill="#15803d">4 fragments · 3 domains · 8 weeks</text>
            <text x={570} y={115} textAnchor="middle" fontSize={10} fill="#15803d">→ Dark Edge Hypothesis: CANDIDATE</text>
            <text x={570} y={132} textAnchor="middle" fontSize={9} fill="#22c55e">No single pair crossed 0.75 threshold</text>
          </g>
        )}
      </svg>
      <div className="mt-3 grid grid-cols-4 gap-2">
        {[
          { label: "Fragments in view", value: visible.length, color: "text-slate-700" },
          { label: "Affinity edges", value: activeEdges.filter(e => visible.find(v=>v.id===e.from) && visible.find(v=>v.id===e.to)).length, color: "text-blue-600" },
          { label: "Fusion score", value: week >= 5 ? fusionScore.toFixed(3) : "—", color: fusionScore > 0.7 ? "text-green-600" : "text-slate-600" },
          { label: "Status", value: snapped ? "SNAPPED" : "Accumulating", color: snapped ? "text-green-600" : "text-amber-600" },
        ].map((m, i) => (
          <div key={i} className="bg-slate-50 rounded-lg p-2 text-center">
            <div className={`text-lg font-bold ${m.color}`}>{m.value}</div>
            <div className="text-xs text-slate-500">{m.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DecayTab() {
  const W = 660, H = 320, PAD = { t: 30, r: 30, b: 50, l: 55 };
  const profiles = [
    { label: "\"Could not reproduce\" (τ=270d)", tau: 270, base: 0.95, color: "#ef4444", dash: "" },
    { label: "Change records (τ=365d)", tau: 365, base: 0.8, color: "#f59e0b", dash: "" },
    { label: "CLI output (τ=180d)", tau: 180, base: 0.7, color: "#8b5cf6", dash: "6 3" },
    { label: "Self-cleared alarms (τ=90d)", tau: 90, base: 0.7, color: "#3b82f6", dash: "6 3" },
    { label: "Telemetry events (τ=60d)", tau: 60, base: 0.6, color: "#6b7280", dash: "4 2" },
  ];
  const maxDays = 400;
  const x = (d) => PAD.l + (d / maxDays) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - v) * (H - PAD.t - PAD.b);

  return (
    <div className="p-4">
      <h2 className="text-sm font-semibold text-slate-700 mb-1">Decay Profiles by Fragment Source Type</h2>
      <p className="text-xs text-slate-500 mb-3">Telecom-specific decay: change records persist longest, unresolved tickets decay slowest. Near-miss boosts shift curves upward.</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={PAD.l} y1={y(0)} x2={W - PAD.r} y2={y(0)} stroke="#e2e8f0" strokeWidth={1} />
        <line x1={PAD.l} y1={y(0.1)} x2={W - PAD.r} y2={y(0.1)} stroke="#fca5a5" strokeWidth={1} strokeDasharray="4 3" />
        <text x={W - PAD.r + 5} y={y(0.1) + 4} fontSize={9} fill="#ef4444">Expiration floor (0.1)</text>
        {[0, 0.2, 0.4, 0.6, 0.8, 1.0].map((v) => (
          <g key={v}>
            <line x1={PAD.l} y1={y(v)} x2={W - PAD.r} y2={y(v)} stroke="#f1f5f9" strokeWidth={0.5} />
            <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end" fontSize={9} fill="#94a3b8">{v.toFixed(1)}</text>
          </g>
        ))}
        {[0, 90, 180, 270, 365].map((d) => (
          <g key={d}>
            <line x1={x(d)} y1={PAD.t} x2={x(d)} y2={H - PAD.b} stroke="#f1f5f9" strokeWidth={0.5} />
            <text x={x(d)} y={H - PAD.b + 16} textAnchor="middle" fontSize={9} fill="#94a3b8">{d}d</text>
          </g>
        ))}
        <text x={PAD.l - 10} y={PAD.t - 12} fontSize={10} fill="#64748b" fontWeight={600}>Decay Score</text>
        <text x={W / 2} y={H - 5} textAnchor="middle" fontSize={10} fill="#64748b" fontWeight={600}>Days Since Event</text>
        {profiles.map((p, i) => {
          const pts = [];
          for (let d = 0; d <= maxDays; d += 2) {
            const v = p.base * Math.exp(-d / p.tau);
            pts.push(`${x(d)},${y(v)}`);
          }
          return (
            <g key={i}>
              <polyline points={pts.join(" ")} fill="none" stroke={p.color} strokeWidth={2} strokeDasharray={p.dash} />
              <circle cx={x(0)} cy={y(p.base)} r={3} fill={p.color} />
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap gap-3 mt-2 justify-center">
        {profiles.map((p, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <div className="w-5 h-0.5" style={{ backgroundColor: p.color }} />
            <span className="text-xs text-slate-600">{p.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ValueTab() {
  const months = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12"];
  const discoveries = [8, 15, 22, 31, 38, 47, 55, 68, 79, 91, 102, 118];
  const mttrSaved = [12, 35, 67, 110, 158, 221, 289, 372, 461, 560, 672, 801];
  const illumination = [2, 4, 7, 10, 13, 16, 18, 21, 23, 26, 28, 31];
  const licenceSavings = [0, 0, 45, 45, 92, 184, 184, 228, 312, 312, 412, 412];

  const W = 660, H = 280, PAD = { t: 30, r: 80, b: 40, l: 55 };
  const xPos = (i) => PAD.l + (i / (months.length - 1)) * (W - PAD.l - PAD.r);
  const yNorm = (val, max) => PAD.t + (1 - val / max) * (H - PAD.t - PAD.b);

  const maxMttr = 900;
  const maxIllu = 35;

  return (
    <div className="p-4">
      <h2 className="text-sm font-semibold text-slate-700 mb-1">Value Attribution — Cumulative Impact Over 12 Months</h2>
      <p className="text-xs text-slate-500 mb-3">PedkAI's value compounds: every discovery accelerates future incident resolution. The Illumination Ratio shows the growing % of incidents benefiting from PedkAI discoveries.</p>
      <div className="grid grid-cols-4 gap-2 mb-4">
        {[
          { label: "Total Discoveries", value: "118", sub: "Dark nodes, edges, mutations", color: "bg-blue-50 text-blue-700" },
          { label: "MTTR Hours Saved", value: "801", sub: "Cumulative engineer-hours", color: "bg-green-50 text-green-700" },
          { label: "Illumination Ratio", value: "31%", sub: "Incidents touching PedkAI entities", color: "bg-purple-50 text-purple-700" },
          { label: "Licence Savings", value: "£412K", sub: "Phantom CI reclamation", color: "bg-amber-50 text-amber-700" },
        ].map((m, i) => (
          <div key={i} className={`rounded-lg p-3 ${m.color.split(" ")[0]}`}>
            <div className={`text-xl font-bold ${m.color.split(" ")[1]}`}>{m.value}</div>
            <div className="text-xs font-medium text-slate-600">{m.label}</div>
            <div className="text-xs text-slate-400 mt-0.5">{m.sub}</div>
          </div>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {months.map((m, i) => (
          <g key={i}>
            <line x1={xPos(i)} y1={PAD.t} x2={xPos(i)} y2={H - PAD.b} stroke="#f1f5f9" strokeWidth={0.5} />
            <text x={xPos(i)} y={H - PAD.b + 16} textAnchor="middle" fontSize={9} fill="#94a3b8">{m}</text>
          </g>
        ))}
        <polyline points={mttrSaved.map((v, i) => `${xPos(i)},${yNorm(v, maxMttr)}`).join(" ")} fill="none" stroke="#22c55e" strokeWidth={2.5} />
        {mttrSaved.map((v, i) => <circle key={i} cx={xPos(i)} cy={yNorm(v, maxMttr)} r={3} fill="#22c55e" />)}
        <text x={W - PAD.r + 8} y={yNorm(mttrSaved[11], maxMttr) + 4} fontSize={9} fill="#22c55e" fontWeight={600}>MTTR hrs</text>
        <polyline points={illumination.map((v, i) => `${xPos(i)},${yNorm(v, maxIllu)}`).join(" ")} fill="none" stroke="#8b5cf6" strokeWidth={2} strokeDasharray="6 3" />
        {illumination.map((v, i) => <circle key={i} cx={xPos(i)} cy={yNorm(v, maxIllu)} r={3} fill="#8b5cf6" />)}
        <text x={W - PAD.r + 8} y={yNorm(illumination[11], maxIllu) + 4} fontSize={9} fill="#8b5cf6" fontWeight={600}>Illum. %</text>
        {licenceSavings.map((v, i) => (
          <rect key={i} x={xPos(i) - 8} y={yNorm(v, 500)} width={16} height={H - PAD.b - yNorm(v, 500)} fill="rgba(245,158,11,0.3)" rx={2} />
        ))}
        <text x={W - PAD.r + 8} y={yNorm(licenceSavings[11], 500) + 4} fontSize={9} fill="#f59e0b" fontWeight={600}>£K saved</text>
      </svg>
      <div className="mt-3 bg-green-50 rounded-lg p-3 border border-green-200">
        <p className="text-xs text-green-800 font-medium">The Counterfactual Argument</p>
        <p className="text-xs text-green-700 mt-1">
          "Without PedkAI, the 801 engineer-hours of MTTR savings would be time spent hunting for dependencies that PedkAI has already mapped.
          The 31% Illumination Ratio means nearly a third of all incidents now benefit from PedkAI-discovered topology — even when PedkAI takes no active role in the resolution."
        </p>
      </div>
    </div>
  );
}

function ShadowTab() {
  return (
    <div className="p-4">
      <h2 className="text-sm font-semibold text-slate-700 mb-1">Shadow Topology — The Competitive Moat</h2>
      <p className="text-xs text-slate-500 mb-4">PedkAI maintains a private enriched topology. The customer's CMDB gets clean exports. The intelligence stays with PedkAI.</p>
      <svg viewBox="0 0 700 440" className="w-full">
        <rect x={20} y={20} width={310} height={250} rx={8} fill="#fefce8" stroke="#ca8a04" strokeWidth={2} strokeDasharray="6 3" />
        <text x={175} y={45} textAnchor="middle" fontSize={12} fill="#92400e" fontWeight={700}>Shadow Topology (PRIVATE)</text>
        <text x={175} y={62} textAnchor="middle" fontSize={9} fill="#a16207">Never exported to external systems</text>
        {[
          { x: 80, y: 110, label: "LTE-8842-A", type: "CMDB", col: "#93c5fd" },
          { x: 220, y: 100, label: "TN-NW-207", type: "CMDB", col: "#93c5fd" },
          { x: 260, y: 180, label: "VLAN-342", type: "Discovered", col: "#86efac" },
          { x: 100, y: 200, label: "ENB-4421", type: "CMDB", col: "#93c5fd" },
        ].map((n, i) => (
          <g key={i}>
            <circle cx={n.x} cy={n.y} r={22} fill={n.col} stroke={n.type === "Discovered" ? "#22c55e" : "#3b82f6"} strokeWidth={2} />
            <text x={n.x} y={n.y - 2} textAnchor="middle" fontSize={7} fill="#1e293b" fontWeight={600}>{n.label}</text>
            <text x={n.x} y={n.y + 9} textAnchor="middle" fontSize={6} fill="#475569">{n.type}</text>
          </g>
        ))}
        <line x1={102} y1={110} x2={198} y2={100} stroke="#3b82f6" strokeWidth={1.5} />
        <line x1={100} y1={178} x2={80} y2={132} stroke="#3b82f6" strokeWidth={1.5} />
        <line x1={120} y1={198} x2={200} y2={106} stroke="#22c55e" strokeWidth={2.5} strokeDasharray="none" />
        <text x={165} y={145} textAnchor="middle" fontSize={8} fill="#16a34a" fontWeight={700}>Dark Edge</text>
        <text x={165} y={155} textAnchor="middle" fontSize={7} fill="#16a34a">(PedkAI discovered)</text>
        <line x1={238} y1={180} x2={222} y2={122} stroke="#22c55e" strokeWidth={2.5} />
        <rect x={50} y={235} width={240} height={28} rx={4} fill="#fef9c3" />
        <text x={170} y={253} textAnchor="middle" fontSize={8} fill="#854d0e">+ confidence scores, evidence chains, fragment refs,</text>
        <text x={170} y={263} textAnchor="middle" fontSize={8} fill="#854d0e">scoring calibration, accumulation graph state</text>

        <g>
          <rect x={360} y={100} width={30} height={130} rx={4} fill="#e2e8f0" />
          <text x={375} y={170} textAnchor="middle" fontSize={20} fill="#64748b">→</text>
          <text x={375} y={90} textAnchor="middle" fontSize={8} fill="#64748b" fontWeight={600}>Controlled</text>
          <text x={375} y={100} textAnchor="middle" fontSize={8} fill="#64748b" fontWeight={600}>Export</text>
        </g>

        <rect x={410} y={70} width={270} height={200} rx={8} fill="#eff6ff" stroke="#3b82f6" strokeWidth={1.5} />
        <text x={545} y={95} textAnchor="middle" fontSize={12} fill="#1e40af" fontWeight={700}>Customer CMDB</text>
        <text x={545} y={112} textAnchor="middle" fontSize={9} fill="#3b82f6">ServiceNow / BMC / Datagerry</text>
        <text x={545} y={140} textAnchor="middle" fontSize={9} fill="#334155">Receives:</text>
        {[
          "✓ CI record + relationship",
          "✓ PedkAI reference tag",
          "✓ Discovery timestamp",
          "✓ Human-readable summary",
          "",
          "✗ NO confidence scores",
          "✗ NO evidence chains",
          "✗ NO fragment references",
          "✗ NO scoring methodology",
        ].map((line, i) => (
          <text key={i} x={460} y={155 + i * 13} fontSize={9} fill={line.startsWith("✗") ? "#dc2626" : line.startsWith("✓") ? "#16a34a" : "#334155"}>
            {line}
          </text>
        ))}

        <rect x={20} y={300} width={660} height={120} rx={8} fill="#f0fdf4" stroke="#22c55e" strokeWidth={1.5} />
        <text x={350} y={325} textAnchor="middle" fontSize={12} fill="#15803d" fontWeight={700}>The Flywheel Effect</text>
        {[
          { x: 80, m: "Month 1", desc: "Shadow = CMDB only\n3-hop enrichment", opacity: 0.4 },
          { x: 240, m: "Month 6", desc: "Shadow = CMDB + 47\n5-hop enrichment", opacity: 0.7 },
          { x: 420, m: "Month 12", desc: "Shadow = CMDB + 183\n8-hop enrichment", opacity: 1.0 },
          { x: 590, m: "Competitor", desc: "Starts at Month 1\n12 months behind", opacity: 0.3 },
        ].map((s, i) => (
          <g key={i} opacity={s.opacity}>
            <rect x={s.x - 55} y={340} width={110} height={65} rx={6} fill="white" stroke="#86efac" strokeWidth={1.5} />
            <text x={s.x} y={357} textAnchor="middle" fontSize={10} fill="#15803d" fontWeight={700}>{s.m}</text>
            {s.desc.split("\n").map((l, j) => (
              <text key={j} x={s.x} y={372 + j * 13} textAnchor="middle" fontSize={9} fill="#475569">{l}</text>
            ))}
          </g>
        ))}
        <line x1={135} y1={370} x2={175} y2={370} stroke="#22c55e" strokeWidth={2} markerEnd="url(#arrow)" />
        <line x1={305} y1={370} x2={355} y2={370} stroke="#22c55e" strokeWidth={2} />
        <text x={590} y={398} textAnchor="middle" fontSize={8} fill="#dc2626" fontWeight={600}>Gap widens over time</text>
      </svg>
    </div>
  );
}
