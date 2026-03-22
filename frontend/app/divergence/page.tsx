"use client";

import React, { useEffect, useState, useCallback, useMemo, useRef } from "react";
import {
  AlertTriangle,
  Eye,
  EyeOff,
  Layers,
  Link2,
  Link2Off,
  Play,
  RefreshCw,
  Shield,
  Activity,
  FlaskConical,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  ExternalLink,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  BarChart3,
  Target,
  TrendingUp,
  X,
  ChevronLeft,
  Brain,
  Cpu,
  Network,
  Wrench,
  Sparkles,
} from "lucide-react";
import { useAuth } from "@/app/context/AuthContext";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// ── Type colours ────────────────────────────────────────────────────────────
const TYPE_META: Record<
  string,
  {
    label: string;
    colour: string;
    colourBg: string;
    hex: string;
    icon: React.ElementType;
    desc: string;
  }
> = {
  dark_node: {
    label: "Dark Nodes",
    colour: "text-red-400",
    colourBg: "bg-red-500/15 border-red-500/30",
    hex: "#f87171",
    icon: Eye,
    desc: "Entities seen in signals but absent from CMDB",
  },
  phantom_node: {
    label: "Phantom Nodes",
    colour: "text-amber-400",
    colourBg: "bg-amber-500/15 border-amber-500/30",
    hex: "#fbbf24",
    icon: EyeOff,
    desc: "CMDB entities with zero operational footprint",
  },
  identity_mutation: {
    label: "Identity Mutations",
    colour: "text-violet-400",
    colourBg: "bg-violet-500/15 border-violet-500/30",
    hex: "#a78bfa",
    icon: Shield,
    desc: "Hardware fingerprint swap or identity collision",
  },
  dark_attribute: {
    label: "Dark Attributes",
    colour: "text-blue-400",
    colourBg: "bg-blue-500/15 border-blue-500/30",
    hex: "#60a5fa",
    icon: Layers,
    desc: "KPI metadata contradicts CMDB-declared attributes",
  },
  dark_edge: {
    label: "Dark Edges",
    colour: "text-cyan-400",
    colourBg: "bg-cyan-500/15 border-cyan-500/30",
    hex: "#22d3ee",
    icon: Link2,
    desc: "Neighbour relations not in CMDB topology",
  },
  phantom_edge: {
    label: "Phantom Edges",
    colour: "text-orange-400",
    colourBg: "bg-orange-500/15 border-orange-500/30",
    hex: "#fb923c",
    icon: Link2Off,
    desc: "CMDB topology edges where neither endpoint shows activity",
  },
};

const TYPE_ORDER = [
  "dark_node",
  "phantom_node",
  "identity_mutation",
  "dark_attribute",
  "dark_edge",
  "phantom_edge",
];

const DOMAIN_LABELS: Record<string, string> = {
  mobile_ran: "Mobile RAN",
  fixed_access: "Fixed Access",
  transport: "Transport",
  logical_service: "Logical Service",
  core: "Core",
  power_environment: "Power / Env",
  cross_domain: "Cross-Domain",
};

const DOMAIN_COLOURS: Record<string, string> = {
  mobile_ran: "#22d3ee",
  fixed_access: "#a78bfa",
  transport: "#60a5fa",
  logical_service: "#34d399",
  core: "#f87171",
  power_environment: "#fbbf24",
  cross_domain: "#fb923c",
};

// ── Views ───────────────────────────────────────────────────────────────────
type ViewMode = "summary" | "explore" | "table";

// ── API helpers ─────────────────────────────────────────────────────────────
async function apiFetch(path: string, token: string, opts?: RequestInit) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(opts?.headers ?? {}),
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Copy button ─────────────────────────────────────────────────────────────
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center text-white/60 hover:text-white/80 transition-colors"
      title="Copy to clipboard"
    >
      {copied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

// ── Horizontal bar (reusable) ───────────────────────────────────────────────
function HBar({
  items,
  onItemClick,
}: {
  items: { label: string; value: number; colour: string; key: string }[];
  onItemClick?: (key: string) => void;
}) {
  const total = items.reduce((s, i) => s + i.value, 0) || 1;
  return (
    <div className="space-y-1.5">
      {items.map((item) => {
        const pct = Math.round((item.value / total) * 100);
        return (
          <button
            key={item.key}
            onClick={() => onItemClick?.(item.key)}
            className="w-full flex items-center gap-3 text-sm group hover:bg-white/5 rounded-lg px-2 py-1 transition-colors"
          >
            <span className="w-36 text-right text-white/80 text-xs shrink-0 truncate">
              {item.label}
            </span>
            <div className="flex-1 bg-[#06203b] rounded-full h-2.5 overflow-hidden">
              <div
                className="h-2.5 rounded-full transition-all group-hover:brightness-125"
                style={{ width: `${Math.max(pct, 1)}%`, backgroundColor: item.colour }}
              />
            </div>
            <span className="w-24 text-white text-xs text-right tabular-nums">
              {item.value.toLocaleString()}{" "}
              <span className="text-white/70">({pct}%)</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ── Donut chart (pure CSS) ──────────────────────────────────────────────────
function DonutChart({
  segments,
  total,
  label,
  onClick,
}: {
  segments: { key: string; value: number; colour: string; label: string }[];
  total: number;
  label: string;
  onClick?: (key: string) => void;
}) {
  const size = 160;
  const stroke = 24;
  const radius = (size - stroke) / 2;
  const circ = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={size} height={size} className="transform -rotate-90">
        {segments
          .filter((s) => s.value > 0)
          .map((seg) => {
            const pct = seg.value / (total || 1);
            const dash = pct * circ;
            const el = (
              <circle
                key={seg.key}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={seg.colour}
                strokeWidth={stroke}
                strokeDasharray={`${dash} ${circ - dash}`}
                strokeDashoffset={-offset}
                className="cursor-pointer hover:opacity-80 transition-opacity"
                onClick={() => onClick?.(seg.key)}
              />
            );
            offset += dash;
            return el;
          })}
        {total === 0 && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="#1e3a5f"
            strokeWidth={stroke}
          />
        )}
      </svg>
      <div className="text-center -mt-[104px] mb-[60px]">
        <div className="text-xl font-bold text-white">{total.toLocaleString()}</div>
        <div className="text-[10px] text-white/70 uppercase tracking-wider">{label}</div>
      </div>
    </div>
  );
}

// ── Confidence badge ────────────────────────────────────────────────────────
function ConfBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const cls =
    pct >= 90
      ? "text-red-400 bg-red-500/15"
      : pct >= 70
        ? "text-amber-400 bg-amber-500/15"
        : pct >= 50
          ? "text-blue-400 bg-blue-500/15"
          : "text-white/60 bg-white/5";
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium tabular-nums ${cls}`}>
      {pct}%
    </span>
  );
}

// ── Score badge (evaluation) ────────────────────────────────────────────────
function ScoreBadge({ label, value }: { label: string; value: number | null }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const colour =
    pct >= 80
      ? "text-green-400 bg-green-500/15 border-green-500/30"
      : pct >= 50
        ? "text-amber-400 bg-amber-500/15 border-amber-500/30"
        : "text-red-400 bg-red-500/15 border-red-500/30";
  return (
    <div className={`flex flex-col items-center rounded-xl border px-5 py-3 ${colour}`}>
      <span className="text-2xl font-bold">{pct}%</span>
      <span className="text-xs text-white/80 mt-0.5">{label}</span>
    </div>
  );
}

// ── Entity link ─────────────────────────────────────────────────────────────
function EntityLink({
  targetId,
  entityName,
  externalId,
}: {
  targetId: string;
  entityName?: string | null;
  externalId?: string | null;
}) {
  const displayName = entityName || externalId || targetId;
  const href = `/topology?entity_id=${encodeURIComponent(targetId)}`;
  const openTopology = (e: React.MouseEvent) => {
    e.preventDefault();
    window.open(href, "pedkai_workspace");
  };
  return (
    <span className="inline-flex items-center gap-1.5 max-w-[280px]">
      <a
        href={href}
        onClick={openTopology}
        className="text-cyan-400 hover:text-cyan-300 hover:underline underline-offset-2 transition-colors truncate text-xs font-medium"
        title={`Open in topology: ${entityName || targetId}`}
      >
        {displayName}
      </a>
      <CopyButton text={entityName || externalId || targetId} />
      <a
        href={href}
        onClick={openTopology}
        className="text-white/30 hover:text-cyan-400 transition-colors shrink-0"
        title="Open in topology"
      >
        <ExternalLink className="w-3 h-3" />
      </a>
    </span>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═════════════════════════════════════════════════════════════════════════════
export default function DivergencePage() {
  const { tenantId, token } = useAuth();

  // Data state
  const [summary, setSummary] = useState<any>(null);
  const [aggregations, setAggregations] = useState<any>(null);
  const [score, setScore] = useState<any>(null);
  const [records, setRecords] = useState<any[]>([]);
  const [totalRecords, setTotalRecords] = useState(0);

  // UI state
  const [view, setView] = useState<ViewMode>("summary");
  const [page, setPage] = useState(1);
  const [filterType, setFilterType] = useState<string>("");
  const [filterDomain, setFilterDomain] = useState<string>("");
  const [filterTargetType, setFilterTargetType] = useState<string>("");
  const [sortBy, setSortBy] = useState<string>("confidence");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [showEval, setShowEval] = useState(false);

  // Evidence panel state
  const [evidence, setEvidence] = useState<Record<string, any>>({});
  const [loadingEvidence, setLoadingEvidence] = useState<string | null>(null);

  // Enriched profile state (intelligence/inference)
  const [enrichedProfiles, setEnrichedProfiles] = useState<Record<string, any>>({});
  const [loadingEnriched, setLoadingEnriched] = useState<string | null>(null);

  // Loading state
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Async job polling state
  const [jobId, setJobId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const PAGE_SIZE = 50;

  // ── Fetch evidence for a specific divergence record ─────────────────────
  const fetchEvidence = useCallback(
    async (resultId: string) => {
      if (!token || evidence[resultId]) return;
      setLoadingEvidence(resultId);
      try {
        const data = await apiFetch(
          `/api/v1/reports/divergence/evidence/${encodeURIComponent(resultId)}`,
          token,
        );
        setEvidence((prev) => ({ ...prev, [resultId]: data }));
      } catch (e) {
        console.error("Evidence fetch failed:", e);
      } finally {
        setLoadingEvidence(null);
      }
    },
    [token, evidence],
  );

  // ── Fetch enriched profile (intelligence/inference) ──────────────────
  const fetchEnrichedProfile = useCallback(
    async (resultId: string) => {
      if (!token || enrichedProfiles[resultId]) return;
      setLoadingEnriched(resultId);
      try {
        const data = await apiFetch(
          `/api/v1/reports/divergence/enriched-profile/${encodeURIComponent(resultId)}`,
          token,
        );
        setEnrichedProfiles((prev) => ({ ...prev, [resultId]: data }));
      } catch (e) {
        console.error("Enriched profile fetch failed:", e);
        setEnrichedProfiles((prev) => ({ ...prev, [resultId]: { error: true } }));
      } finally {
        setLoadingEnriched(null);
      }
    },
    [token, enrichedProfiles],
  );

  // ── Fetch summary ──────────────────────────────────────────────────────
  const fetchSummary = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      const s = await apiFetch(
        `/api/v1/reports/divergence/summary`,
        token,
      );
      setSummary(s);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  // ── Fetch aggregations ─────────────────────────────────────────────────
  const fetchAggregations = useCallback(async () => {
    if (!token) return;
    try {
      const a = await apiFetch(
        `/api/v1/reports/divergence/aggregations`,
        token,
      );
      setAggregations(a);
    } catch {
      setAggregations(null);
    }
  }, [token]);

  // ── Fetch evaluation score ─────────────────────────────────────────────
  const fetchScore = useCallback(async () => {
    if (!tenantId || !token) return;
    try {
      const sc = await apiFetch(
        `/api/v1/reports/divergence/score/${encodeURIComponent(tenantId)}`,
        token,
      );
      setScore(sc);
    } catch {
      setScore(null);
    }
  }, [tenantId, token]);

  // ── Fetch records page ─────────────────────────────────────────────────
  const fetchRecords = useCallback(async () => {
    if (!token) return;
    let path = `/api/v1/reports/divergence/records?page=${page}&page_size=${PAGE_SIZE}`;
    if (filterType) path += `&divergence_type=${encodeURIComponent(filterType)}`;
    if (filterDomain) path += `&domain=${encodeURIComponent(filterDomain)}`;
    if (filterTargetType) path += `&target_type=${encodeURIComponent(filterTargetType)}`;
    path += `&sort_by=${sortBy}&sort_dir=${sortDir}`;
    try {
      const data = await apiFetch(path, token);
      setRecords(data.records ?? []);
      setTotalRecords(data.total ?? 0);
    } catch {
      setRecords([]);
    }
  }, [token, page, filterType, filterDomain, filterTargetType, sortBy, sortDir]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  useEffect(() => {
    if (summary) {
      fetchAggregations();
    }
  }, [summary, fetchAggregations]);

  useEffect(() => {
    if (summary && view === "table") fetchRecords();
  }, [summary, view, fetchRecords]);

  // ── Run reconciliation (async job with polling) ────────────────────────
  async function handleRun() {
    if (!token) return;
    setRunning(true);
    setRunError(null);
    setJobId(null);

    // Clear any previous poll
    if (pollRef.current) clearInterval(pollRef.current);

    try {
      const res = await apiFetch(`/api/v1/reports/divergence/run`, token, {
        method: "POST",
        body: JSON.stringify({}),
      });

      const id: string = res.job_id;
      setJobId(id);

      // Poll every 5s until complete or failed
      pollRef.current = setInterval(async () => {
        try {
          const job = await apiFetch(
            `/api/v1/reports/divergence/run/${encodeURIComponent(id)}`,
            token,
          );

          if (job.status === "complete") {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setRunning(false);
            setJobId(null);
            // Refresh all views
            setPage(1);
            setFilterType("");
            setFilterDomain("");
            setFilterTargetType("");
            setScore(null);
            setShowEval(false);
            setAggregations(null);
            setView("summary");
            await fetchSummary();
          } else if (job.status === "failed") {
            clearInterval(pollRef.current!);
            pollRef.current = null;
            setRunning(false);
            setJobId(null);
            setRunError(job.error ?? "Reconciliation failed.");
          }
          // status === "running" → keep polling
        } catch (pollErr: any) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setRunning(false);
          setJobId(null);
          setRunError(pollErr.message);
        }
      }, 5000);
    } catch (e: any) {
      setRunning(false);
      setRunError(e.message);
    }
  }

  // Clean up poll on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ── Drill-down handlers ────────────────────────────────────────────────
  function drillToType(type: string) {
    setFilterType(type);
    setFilterDomain("");
    setFilterTargetType("");
    setPage(1);
    setView("table");
  }

  function drillToDomain(domain: string) {
    setFilterDomain(domain);
    setPage(1);
    setView("table");
  }

  function drillToTargetType(targetType: string) {
    setFilterTargetType(targetType);
    setPage(1);
    setView("table");
  }

  // ── Sort handler ───────────────────────────────────────────────────────
  function handleSort(col: string) {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
    setPage(1);
  }

  function SortIcon({ col }: { col: string }) {
    if (sortBy !== col) return <ArrowUpDown className="w-3 h-3 text-white/30" />;
    return sortDir === "asc" ? (
      <ArrowUp className="w-3 h-3 text-cyan-400" />
    ) : (
      <ArrowDown className="w-3 h-3 text-cyan-400" />
    );
  }

  // ── Derived data ───────────────────────────────────────────────────────
  const domains = summary ? Object.keys(summary.summary?.by_domain ?? {}) : [];
  const inv = summary?.operational_inventory;
  const byType = summary?.summary?.by_type ?? {};
  const totalDiv = summary?.summary?.total_divergences ?? 0;

  // Aggregate target types for filter dropdown
  const targetTypes = useMemo(() => {
    if (!aggregations?.type_target) return [];
    const types = new Map<string, number>();
    for (const row of aggregations.type_target) {
      types.set(row.target_type, (types.get(row.target_type) || 0) + row.count);
    }
    return Array.from(types.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 30)
      .map(([t, c]) => ({ type: t, count: c }));
  }, [aggregations]);

  // Top entity types per divergence type (for explore view)
  const typeTargetMap = useMemo(() => {
    if (!aggregations?.type_target) return {};
    const map: Record<string, { target_type: string; count: number }[]> = {};
    for (const row of aggregations.type_target) {
      if (!map[row.type]) map[row.type] = [];
      map[row.type].push({ target_type: row.target_type, count: row.count });
    }
    return map;
  }, [aggregations]);

  // ══════════════════════════════════════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════════════════════════════════════
  return (
    <div className="min-h-screen text-white">
      <div className="max-w-screen-2xl mx-auto px-6 py-8 space-y-6">

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Dark Graph Reconciliation
            </h1>
            <p className="mt-1 text-white/80 text-sm">
              CMDB declarations vs operational signals -- detecting divergences
              from KPI telemetry, alarms, and neighbour relations.
            </p>
          </div>
          <button
            onClick={handleRun}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-400 hover:bg-cyan-300 disabled:opacity-50 transition-colors text-sm font-bold text-gray-950 shrink-0"
          >
            {running ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {running ? "Running..." : "Run Reconciliation"}
          </button>
        </div>

        {running && (
          <div className="p-3 rounded-lg bg-cyan-900/30 border border-cyan-700/50 text-cyan-300 text-sm flex items-center gap-3">
            <RefreshCw className="w-4 h-4 animate-spin shrink-0" />
            <span>
              Reconciliation in progress — scanning CMDB against operational signals.
              This takes several minutes on large datasets.
              {jobId && <span className="ml-2 text-cyan-400/60 font-mono text-xs">job: {jobId}</span>}
            </span>
          </div>
        )}

        {runError && (
          <div className="p-3 rounded-lg bg-red-900/40 border border-red-700 text-red-300 text-sm">
            {runError}
          </div>
        )}

        {/* ── Empty state ─────────────────────────────────────────────── */}
        {!loading && error && (
          <div className="flex flex-col items-center justify-center py-32 text-center space-y-4">
            <AlertTriangle className="w-12 h-12 text-amber-400" />
            <p className="text-white text-lg">No reconciliation run found.</p>
            <p className="text-white/60 text-sm">
              Click <strong className="text-white">Run Reconciliation</strong> to
              analyse operational signals against the CMDB.
            </p>
          </div>
        )}

        {loading && !error && (
          <div className="flex justify-center py-32">
            <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
          </div>
        )}

        {summary && !error && (
          <>
            {/* ── Run metadata + view tabs ─────────────────────────────── */}
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-4 text-xs text-white/70">
                <span>
                  Run:{" "}
                  <span className="font-mono text-white">
                    {summary.run_id?.slice(0, 8)}
                  </span>
                </span>
                {summary.run_at && (
                  <span>
                    {new Date(summary.run_at).toLocaleString("en-GB")}
                  </span>
                )}
                {summary.duration_seconds != null && (
                  <span>{Math.round(summary.duration_seconds)}s</span>
                )}
              </div>
              <div className="flex gap-1 bg-[#06203b] rounded-lg p-0.5">
                {[
                  { key: "summary" as ViewMode, label: "Summary", icon: BarChart3 },
                  { key: "explore" as ViewMode, label: "Explore", icon: Target },
                  { key: "table" as ViewMode, label: "Records", icon: Layers },
                ].map(({ key, label, icon: Icon }) => (
                  <button
                    key={key}
                    onClick={() => setView(key)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                      view === key
                        ? "bg-cyan-400/15 text-cyan-400"
                        : "text-white/60 hover:text-white/80 hover:bg-white/5"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* ════════════════════════════════════════════════════════════
                SUMMARY VIEW (Executive Dashboard)
                ════════════════════════════════════════════════════════════ */}
            {view === "summary" && (
              <div className="space-y-6">

                {/* Hero number + type distribution donut */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

                  {/* Left: total + donut */}
                  <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-6 flex flex-col items-center justify-center gap-4">
                    <DonutChart
                      segments={TYPE_ORDER.filter((t) => (byType[t] ?? 0) > 0).map((t) => ({
                        key: t,
                        value: byType[t] ?? 0,
                        colour: TYPE_META[t].hex,
                        label: TYPE_META[t].label,
                      }))}
                      total={totalDiv}
                      label="Total Divergences"
                      onClick={drillToType}
                    />
                    <div className="flex flex-wrap justify-center gap-x-4 gap-y-1">
                      {TYPE_ORDER.filter((t) => (byType[t] ?? 0) > 0).map((t) => (
                        <button
                          key={t}
                          onClick={() => drillToType(t)}
                          className="flex items-center gap-1.5 text-xs hover:brightness-125 transition-all"
                        >
                          <span
                            className="w-2.5 h-2.5 rounded-full"
                            style={{ backgroundColor: TYPE_META[t].hex }}
                          />
                          <span className="text-white/80">{TYPE_META[t].label}</span>
                          <span className="text-white/70">
                            {(byType[t] ?? 0).toLocaleString()}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Center: type stat cards */}
                  <div className="lg:col-span-2 grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {TYPE_ORDER.map((t) => {
                      const meta = TYPE_META[t];
                      const count = byType[t] ?? 0;
                      const pct = totalDiv ? Math.round((count / totalDiv) * 100) : 0;
                      const Icon = meta.icon;
                      return (
                        <button
                          key={t}
                          onClick={() => drillToType(t)}
                          className={`rounded-xl border p-4 flex flex-col gap-1 text-left transition-all hover:brightness-110 hover:scale-[1.02] ${meta.colourBg}`}
                        >
                          <div className="flex items-center gap-2">
                            <Icon className={`w-4 h-4 ${meta.colour}`} />
                            <span className="text-xs text-white/60 uppercase tracking-wider font-semibold">
                              {meta.label}
                            </span>
                          </div>
                          <span className={`text-2xl font-bold ${meta.colour}`}>
                            {count.toLocaleString()}
                          </span>
                          <span className="text-xs text-white/70">
                            {pct}% of total -- {meta.desc}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Operational inventory */}
                {inv && (
                  <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-4">
                    <div className="flex items-center gap-2">
                      <Activity className="w-5 h-5 text-blue-400" />
                      <h2 className="font-semibold text-white">Operational Inventory</h2>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                      {([
                        ["CMDB entities", inv.cmdb_entity_count, "Declared in CMDB"],
                        ["Observed entities", inv.observed_entity_count, "Seen in signals"],
                        ["CMDB edges", inv.cmdb_edge_count, "Declared topology"],
                        ["Observed edges", inv.observed_edge_count, "Neighbour relations"],
                      ] as [string, number, string][]).map(([lbl, val, sub]) => (
                        <div key={lbl} className="bg-white/8 rounded-lg p-3">
                          <div className="text-white/80 text-xs">{lbl}</div>
                          <div className="text-white font-bold mt-0.5">{val?.toLocaleString()}</div>
                          <div className="text-white/70 text-xs">{sub}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Domain breakdown */}
                {domains.length > 0 && (
                  <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-3">
                    <h2 className="font-semibold text-white text-sm">Divergences by Domain</h2>
                    <HBar
                      items={domains
                        .sort((a, b) => (summary.summary.by_domain[b] ?? 0) - (summary.summary.by_domain[a] ?? 0))
                        .map((d) => ({
                          key: d,
                          label: DOMAIN_LABELS[d] ?? d,
                          value: summary.summary.by_domain[d] ?? 0,
                          colour: DOMAIN_COLOURS[d] ?? "#60a5fa",
                        }))}
                      onItemClick={drillToDomain}
                    />
                  </div>
                )}

                {/* Key divergences */}
                {aggregations?.key_divergences?.length > 0 && (
                  <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-3">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-5 h-5 text-red-400" />
                      <h2 className="font-semibold text-white text-sm">
                        Key Divergences
                      </h2>
                      <span className="text-xs text-white/70 ml-1">
                        Highest confidence findings
                      </span>
                    </div>
                    <div className="space-y-2">
                      {aggregations.key_divergences.slice(0, 10).map((d: any) => {
                        const meta = TYPE_META[d.divergence_type];
                        const Icon = meta?.icon ?? AlertTriangle;
                        return (
                          <div
                            key={d.result_id}
                            className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.03] hover:bg-white/5 transition-colors"
                          >
                            <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${meta?.colour ?? "text-white"}`} />
                            <div className="flex-1 min-w-0 space-y-1">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className={`text-xs font-medium ${meta?.colour}`}>
                                  {meta?.label}
                                </span>
                                <ConfBadge value={d.confidence} />
                                {d.entity_name && (
                                  <EntityLink
                                    targetId={d.target_id}
                                    entityName={d.entity_name}
                                    externalId={d.external_id}
                                  />
                                )}
                              </div>
                              <p className="text-xs text-white/70 leading-relaxed">
                                {d.description}
                              </p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Top affected entities */}
                {aggregations?.top_entities?.length > 0 && (
                  <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-3">
                    <h2 className="font-semibold text-white text-sm">
                      Most Affected Entities
                    </h2>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-white/70 text-left border-b border-cyan-900/40">
                            <th className="pb-2 pr-3">Entity</th>
                            <th className="pb-2 pr-3">Type</th>
                            <th className="pb-2 pr-3">Domain</th>
                            <th className="pb-2 pr-3 text-right">Divergences</th>
                            <th className="pb-2 text-right">Avg Confidence</th>
                          </tr>
                        </thead>
                        <tbody>
                          {aggregations.top_entities.slice(0, 10).map((e: any, i: number) => (
                            <tr key={i} className="border-b border-cyan-900/20 hover:bg-white/5 transition-colors">
                              <td className="py-2 pr-3">
                                <EntityLink
                                  targetId={e.target_id}
                                  entityName={e.entity_name}
                                  externalId={e.external_id}
                                />
                              </td>
                              <td className="py-2 pr-3 text-white/80 font-mono">{e.target_type}</td>
                              <td className="py-2 pr-3 text-white/80">
                                {DOMAIN_LABELS[e.domain] ?? e.domain}
                              </td>
                              <td className="py-2 pr-3 text-right text-white font-medium">
                                {e.divergence_count}
                              </td>
                              <td className="py-2 text-right">
                                {e.avg_confidence != null && <ConfBadge value={e.avg_confidence} />}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ════════════════════════════════════════════════════════════
                EXPLORE VIEW (Aggregation drill-down)
                ════════════════════════════════════════════════════════════ */}
            {view === "explore" && aggregations && (
              <div className="space-y-6">

                {/* Type x Domain heatmap / breakdown */}
                <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-4">
                  <h2 className="font-semibold text-white text-sm">
                    Divergence Type by Domain
                  </h2>
                  {TYPE_ORDER.filter((t) => (byType[t] ?? 0) > 0).map((t) => {
                    const meta = TYPE_META[t];
                    const Icon = meta.icon;
                    const domainItems = (aggregations.type_domain ?? [])
                      .filter((r: any) => r.type === t)
                      .sort((a: any, b: any) => b.count - a.count);
                    if (domainItems.length === 0) return null;
                    return (
                      <div key={t} className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Icon className={`w-4 h-4 ${meta.colour}`} />
                          <span className={`text-sm font-medium ${meta.colour}`}>
                            {meta.label}
                          </span>
                          <span className="text-xs text-white/70">
                            {(byType[t] ?? 0).toLocaleString()}
                          </span>
                        </div>
                        <HBar
                          items={domainItems.map((r: any) => ({
                            key: `${t}-${r.domain}`,
                            label: DOMAIN_LABELS[r.domain] ?? r.domain,
                            value: r.count,
                            colour: meta.hex,
                          }))}
                          onItemClick={() => drillToType(t)}
                        />
                      </div>
                    );
                  })}
                </div>

                {/* Type x target_type breakdown */}
                <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-4">
                  <h2 className="font-semibold text-white text-sm">
                    Top Affected Entity Types per Divergence
                  </h2>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {TYPE_ORDER.filter((t) => typeTargetMap[t]?.length).map((t) => {
                      const meta = TYPE_META[t];
                      const Icon = meta.icon;
                      const items = (typeTargetMap[t] || []).slice(0, 8);
                      return (
                        <div key={t} className="space-y-2">
                          <div className="flex items-center gap-2">
                            <Icon className={`w-4 h-4 ${meta.colour}`} />
                            <span className={`text-sm font-medium ${meta.colour}`}>
                              {meta.label}
                            </span>
                          </div>
                          <HBar
                            items={items.map((r) => ({
                              key: r.target_type,
                              label: r.target_type,
                              value: r.count,
                              colour: meta.hex,
                            }))}
                            onItemClick={(key) => {
                              setFilterType(t);
                              drillToTargetType(key);
                            }}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Confidence distribution */}
                {aggregations.confidence_buckets?.length > 0 && (
                  <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-4">
                    <h2 className="font-semibold text-white text-sm">Confidence Distribution</h2>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      {["critical", "high", "medium", "low"].map((bucket) => {
                        const total = (aggregations.confidence_buckets ?? [])
                          .filter((b: any) => b.bucket === bucket)
                          .reduce((s: number, b: any) => s + b.count, 0);
                        const bucketColour =
                          bucket === "critical"
                            ? "text-red-400 bg-red-500/15 border-red-500/30"
                            : bucket === "high"
                              ? "text-amber-400 bg-amber-500/15 border-amber-500/30"
                              : bucket === "medium"
                                ? "text-blue-400 bg-blue-500/15 border-blue-500/30"
                                : "text-white/60 bg-white/5 border-white/10";
                        const label =
                          bucket === "critical"
                            ? "90-100%"
                            : bucket === "high"
                              ? "70-89%"
                              : bucket === "medium"
                                ? "50-69%"
                                : "< 50%";
                        return (
                          <div key={bucket} className={`rounded-xl border p-4 ${bucketColour}`}>
                            <div className="text-xs uppercase tracking-wider font-semibold">
                              {bucket}
                            </div>
                            <div className="text-2xl font-bold mt-1">{total.toLocaleString()}</div>
                            <div className="text-xs text-white/80 mt-0.5">{label} confidence</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ════════════════════════════════════════════════════════════
                TABLE VIEW (Records with entity traceability)
                ════════════════════════════════════════════════════════════ */}
            {view === "table" && (
              <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] overflow-hidden">

                {/* Filters bar */}
                <div className="p-4 border-b border-cyan-900/40 flex flex-wrap gap-3 items-center">
                  <span className="text-sm text-white font-medium tabular-nums">
                    {totalRecords.toLocaleString()} divergences
                  </span>

                  {/* Active filter pills */}
                  <div className="flex gap-1.5 flex-wrap">
                    {filterType && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-400/15 text-cyan-400 text-xs">
                        {TYPE_META[filterType]?.label ?? filterType}
                        <button onClick={() => { setFilterType(""); setPage(1); }}>
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    )}
                    {filterDomain && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-400/15 text-cyan-400 text-xs">
                        {DOMAIN_LABELS[filterDomain] ?? filterDomain}
                        <button onClick={() => { setFilterDomain(""); setPage(1); }}>
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    )}
                    {filterTargetType && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-400/15 text-cyan-400 text-xs">
                        {filterTargetType}
                        <button onClick={() => { setFilterTargetType(""); setPage(1); }}>
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    )}
                    {(filterType || filterDomain || filterTargetType) && (
                      <button
                        onClick={() => {
                          setFilterType("");
                          setFilterDomain("");
                          setFilterTargetType("");
                          setPage(1);
                        }}
                        className="text-xs text-white/70 hover:text-white/80 underline"
                      >
                        Clear all
                      </button>
                    )}
                  </div>

                  <div className="flex gap-2 flex-wrap ml-auto">
                    <select
                      value={filterType}
                      onChange={(e) => {
                        setFilterType(e.target.value);
                        setPage(1);
                      }}
                      className="text-xs px-3 py-1.5 rounded-lg bg-[#06203b] border border-cyan-900/50 text-white focus:outline-none focus:ring-1 focus:ring-cyan-400"
                    >
                      <option value="">All types</option>
                      {TYPE_ORDER.map((t) => (
                        <option key={t} value={t}>
                          {TYPE_META[t].label}
                        </option>
                      ))}
                    </select>
                    <select
                      value={filterDomain}
                      onChange={(e) => {
                        setFilterDomain(e.target.value);
                        setPage(1);
                      }}
                      className="text-xs px-3 py-1.5 rounded-lg bg-[#06203b] border border-cyan-900/50 text-white focus:outline-none focus:ring-1 focus:ring-cyan-400"
                    >
                      <option value="">All domains</option>
                      {domains.map((d) => (
                        <option key={d} value={d}>
                          {DOMAIN_LABELS[d] ?? d}
                        </option>
                      ))}
                    </select>
                    <select
                      value={filterTargetType}
                      onChange={(e) => {
                        setFilterTargetType(e.target.value);
                        setPage(1);
                      }}
                      className="text-xs px-3 py-1.5 rounded-lg bg-[#06203b] border border-cyan-900/50 text-white focus:outline-none focus:ring-1 focus:ring-cyan-400"
                    >
                      <option value="">All entity types</option>
                      {targetTypes.map((t) => (
                        <option key={t.type} value={t.type}>
                          {t.type} ({t.count.toLocaleString()})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b border-cyan-900/40 text-xs text-white/60 uppercase tracking-wider bg-[#06203b] sticky top-0 z-10">
                      <tr>
                        <th className="w-8 px-2 py-2" />
                        <th
                          className="text-left px-4 py-2 cursor-pointer hover:text-white/80 select-none"
                          onClick={() => handleSort("divergence_type")}
                        >
                          <span className="inline-flex items-center gap-1">
                            Type <SortIcon col="divergence_type" />
                          </span>
                        </th>
                        <th className="text-left px-4 py-2">Entity</th>
                        <th
                          className="text-left px-4 py-2 cursor-pointer hover:text-white/80 select-none"
                          onClick={() => handleSort("target_type")}
                        >
                          <span className="inline-flex items-center gap-1">
                            Entity Type <SortIcon col="target_type" />
                          </span>
                        </th>
                        <th
                          className="text-left px-4 py-2 cursor-pointer hover:text-white/80 select-none"
                          onClick={() => handleSort("domain")}
                        >
                          <span className="inline-flex items-center gap-1">
                            Domain <SortIcon col="domain" />
                          </span>
                        </th>
                        <th
                          className="text-left px-4 py-2 cursor-pointer hover:text-white/80 select-none"
                          onClick={() => handleSort("confidence")}
                        >
                          <span className="inline-flex items-center gap-1">
                            Confidence <SortIcon col="confidence" />
                          </span>
                        </th>
                        <th className="text-left px-4 py-2">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((r) => {
                        const meta = TYPE_META[r.divergence_type];
                        const Icon = meta?.icon ?? AlertTriangle;
                        const isExpanded = expandedRow === r.result_id;
                        return (
                          <React.Fragment key={r.result_id}>
                            <tr
                              onClick={() => {
                                const newId = isExpanded ? null : r.result_id;
                                setExpandedRow(newId);
                                if (newId) fetchEvidence(newId);
                              }}
                              className={`border-b border-cyan-900/20 cursor-pointer transition-colors ${
                                isExpanded ? "bg-white/[0.06]" : "hover:bg-white/[0.03]"
                              }`}
                            >
                              <td className="px-2 py-2 text-center text-white/60">
                                {isExpanded ? (
                                  <ChevronDown className="w-3.5 h-3.5" />
                                ) : (
                                  <ChevronRight className="w-3.5 h-3.5" />
                                )}
                              </td>
                              <td className="px-4 py-2 whitespace-nowrap">
                                <span
                                  className={`inline-flex items-center gap-1.5 text-xs font-medium ${meta?.colour ?? "text-white"}`}
                                >
                                  <Icon className="w-3.5 h-3.5" />
                                  {meta?.label ?? r.divergence_type}
                                </span>
                              </td>
                              <td className="px-4 py-2">
                                <EntityLink
                                  targetId={r.target_id}
                                  entityName={r.entity_name}
                                  externalId={r.entity_external_id}
                                />
                              </td>
                              <td className="px-4 py-2 text-white/80 text-xs font-mono">
                                {r.target_type ?? "--"}
                              </td>
                              <td className="px-4 py-2 text-white/80 text-xs">
                                {DOMAIN_LABELS[r.domain] ?? r.domain ?? "--"}
                              </td>
                              <td className="px-4 py-2 text-xs">
                                <ConfBadge value={r.confidence ?? 0} />
                              </td>
                              <td className="px-4 py-2 text-white/80 text-xs max-w-md">
                                <span className="line-clamp-2 leading-relaxed">
                                  {r.description}
                                </span>
                              </td>
                            </tr>
                            {/* Expanded detail row */}
                            {isExpanded && (
                              <tr className="bg-white/[0.04]">
                                <td colSpan={7} className="px-8 py-4">
                                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                                    {/* Left column: description + identifiers */}
                                    <div className="space-y-2">
                                      <h4 className="text-white/70 uppercase tracking-wider text-[10px] font-semibold">
                                        Description
                                      </h4>
                                      <p className="text-white/80 leading-relaxed whitespace-pre-wrap">
                                        {r.description}
                                      </p>
                                      <div className="flex gap-4 flex-wrap pt-1">
                                        {r.entity_name || r.entity_external_id ? (
                                          <>
                                            {r.entity_external_id && (
                                              <div>
                                                <span className="text-white/60">External ID: </span>
                                                <span className="font-mono text-white/70">
                                                  {r.entity_external_id}
                                                </span>
                                                <CopyButton text={r.entity_external_id} />
                                              </div>
                                            )}
                                          </>
                                        ) : (
                                          <div>
                                            <span className="text-white/60">Signal ID: </span>
                                            <span className="font-mono text-white/70">
                                              {r.target_id}
                                            </span>
                                            <CopyButton text={r.target_id} />
                                          </div>
                                        )}
                                      </div>
                                    </div>

                                    {/* Right column: evidence panel */}
                                    <div className="space-y-3">
                                      {/* Attribute mismatch (for dark_attribute / identity_mutation) */}
                                      {r.attribute_name && (
                                        <div>
                                          <h4 className="text-white/70 uppercase tracking-wider text-[10px] font-semibold mb-1">
                                            Attribute Mismatch
                                          </h4>
                                          <div className="bg-white/5 rounded-lg p-3 font-mono">
                                            <span className="text-white">
                                              {r.attribute_name}
                                            </span>
                                            <div className="mt-1 space-y-0.5">
                                              <div>
                                                <span className="text-white/60">CMDB: </span>
                                                <span className="text-red-400 line-through">
                                                  {r.cmdb_value}
                                                </span>
                                              </div>
                                              <div>
                                                <span className="text-white/60">Signal: </span>
                                                <span className="text-green-400">
                                                  {r.observed_value}
                                                </span>
                                              </div>
                                            </div>
                                          </div>
                                        </div>
                                      )}

                                      {/* Evidence panel — loaded from API */}
                                      {loadingEvidence === r.result_id && (
                                        <div className="text-white/60 animate-pulse py-2">
                                          Loading evidence...
                                        </div>
                                      )}
                                      {evidence[r.result_id] && (() => {
                                        const ev = evidence[r.result_id];

                                        // Dark Attribute: CMDB + Telemetry evidence
                                        if (r.divergence_type === "dark_attribute" && ev.cmdb && ev.telemetry) {
                                          return (
                                            <div className="space-y-2">
                                              <h4 className="text-white/70 uppercase tracking-wider text-[10px] font-semibold">
                                                Source Evidence
                                              </h4>
                                              <div className="grid grid-cols-2 gap-2">
                                                <div className="bg-white/5 rounded-lg p-3">
                                                  <div className="text-white/60 text-[10px] uppercase mb-1">CMDB Record</div>
                                                  <div className="space-y-0.5">
                                                    {ev.cmdb.entity_name && <div><span className="text-white/60">Name: </span><span className="text-white">{ev.cmdb.entity_name}</span></div>}
                                                    {ev.cmdb.entity_type && <div><span className="text-white/60">Type: </span><span className="text-white font-mono">{ev.cmdb.entity_type}</span></div>}
                                                    {ev.cmdb.vendor && <div><span className="text-white/60">Vendor: </span><span className="text-white">{ev.cmdb.vendor}</span></div>}
                                                    {ev.cmdb.band && <div><span className="text-white/60">Band: </span><span className="text-white">{ev.cmdb.band}</span></div>}
                                                    {ev.cmdb.configured_value && <div><span className="text-white/60">Configured {ev.cmdb.attribute}: </span><span className="text-red-400">{ev.cmdb.configured_value}</span></div>}
                                                  </div>
                                                </div>
                                                <div className="bg-white/5 rounded-lg p-3">
                                                  <div className="text-white/60 text-[10px] uppercase mb-1">Telemetry Evidence</div>
                                                  <div className="space-y-0.5">
                                                    <div><span className="text-white/60">Observed: </span><span className="text-green-400">{ev.telemetry.observed_value}</span></div>
                                                    <div><span className="text-white/60">Samples: </span><span className="text-white">{ev.telemetry.total_samples?.toLocaleString()}</span></div>
                                                    {ev.telemetry.samples?.[0]?.first_seen && (
                                                      <div><span className="text-white/60">First seen: </span><span className="text-white/70">{ev.telemetry.samples[0].first_seen?.split("T")[0]}</span></div>
                                                    )}
                                                    {ev.telemetry.samples?.[0]?.last_seen && (
                                                      <div><span className="text-white/60">Last seen: </span><span className="text-white/70">{ev.telemetry.samples[0].last_seen?.split("T")[0]}</span></div>
                                                    )}
                                                  </div>
                                                </div>
                                              </div>
                                            </div>
                                          );
                                        }

                                        // Dark Edge: neighbour relation + CMDB absence
                                        if (r.divergence_type === "dark_edge" && ev.neighbour_relation) {
                                          const nr = ev.neighbour_relation;
                                          return (
                                            <div className="space-y-2">
                                              <h4 className="text-white/70 uppercase tracking-wider text-[10px] font-semibold">
                                                Traffic Evidence
                                              </h4>
                                              <div className="bg-white/5 rounded-lg p-3 space-y-1">
                                                <div><span className="text-white/60">From: </span><span className="text-white">{nr.from_cell}</span></div>
                                                <div><span className="text-white/60">To: </span><span className="text-white">{nr.to_cell}</span></div>
                                                {nr.neighbour_type && <div><span className="text-white/60">Type: </span><span className="text-white font-mono">{nr.neighbour_type}</span></div>}
                                                {nr.handover_attempts != null && <div><span className="text-white/60">Handover attempts: </span><span className="text-white">{nr.handover_attempts?.toLocaleString()}</span></div>}
                                                {nr.handover_success_rate != null && <div><span className="text-white/60">Success rate: </span><span className="text-white">{(nr.handover_success_rate * 100).toFixed(1)}%</span></div>}
                                              </div>
                                              <div className="bg-white/5 rounded-lg p-3">
                                                <div className="text-white/60 text-[10px] uppercase mb-1">CMDB Status</div>
                                                <span className={ev.cmdb_edge_exists ? "text-amber-400" : "text-red-400"}>
                                                  {ev.cmdb_edge_exists ? "Edge exists in CMDB" : "No matching edge in CMDB topology"}
                                                </span>
                                              </div>
                                            </div>
                                          );
                                        }

                                        // Phantom Node: signal absence proof
                                        if (r.divergence_type === "phantom_node" && ev.signal_check) {
                                          const sc = ev.signal_check;
                                          return (
                                            <div className="space-y-2">
                                              <h4 className="text-white/70 uppercase tracking-wider text-[10px] font-semibold">
                                                Signal Absence Proof
                                              </h4>
                                              <div className="bg-white/5 rounded-lg p-3 space-y-1">
                                                <div><span className="text-white/60">KPI samples: </span><span className={sc.kpi_samples === 0 ? "text-red-400" : "text-green-400"}>{sc.kpi_samples}</span></div>
                                                <div><span className="text-white/60">Alarm events: </span><span className={sc.alarm_events === 0 ? "text-red-400" : "text-green-400"}>{sc.alarm_events}</span></div>
                                                <div><span className="text-white/60">Neighbour relations: </span><span className={sc.neighbour_relations === 0 ? "text-red-400" : "text-green-400"}>{sc.neighbour_relations}</span></div>
                                                <div className="pt-1 border-t border-white/10 mt-1">
                                                  <span className="text-white/60">Detection: </span>
                                                  <span className="text-white/70">{sc.detection_method} (entity name not used)</span>
                                                </div>
                                              </div>
                                              {ev.cmdb && (
                                                <div className="bg-white/5 rounded-lg p-3">
                                                  <div className="text-white/60 text-[10px] uppercase mb-1">CMDB Record</div>
                                                  {ev.cmdb.entity_name && <div><span className="text-white/60">Name: </span><span className="text-white">{ev.cmdb.entity_name}</span></div>}
                                                  {ev.cmdb.entity_type && <div><span className="text-white/60">Type: </span><span className="text-white font-mono">{ev.cmdb.entity_type}</span></div>}
                                                </div>
                                              )}
                                            </div>
                                          );
                                        }

                                        // Dark Node: signal source summary
                                        if (r.divergence_type === "dark_node" && ev.signal_summary) {
                                          const ss = ev.signal_summary;
                                          return (
                                            <div className="space-y-2">
                                              <h4 className="text-white/70 uppercase tracking-wider text-[10px] font-semibold">
                                                Signal Source
                                              </h4>
                                              {ss.kpi_profiles?.length > 0 && (
                                                <div className="bg-white/5 rounded-lg p-3 space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase mb-1">KPI Telemetry</div>
                                                  {ss.kpi_profiles.map((p: any, i: number) => (
                                                    <div key={i} className="flex gap-3 text-white/80">
                                                      {p.domain && <span>{p.domain}</span>}
                                                      {p.vendor && <span className="text-white/60">{p.vendor}</span>}
                                                      {p.rat_type && <span className="text-white/60">{p.rat_type}</span>}
                                                      <span className="text-white/60 ml-auto">{p.sample_count?.toLocaleString()} samples</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              )}
                                              {ss.alarm_profiles?.length > 0 && (
                                                <div className="bg-white/5 rounded-lg p-3 space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase mb-1">Alarms</div>
                                                  {ss.alarm_profiles.map((p: any, i: number) => (
                                                    <div key={i} className="flex gap-3 text-white/80">
                                                      {p.domain && <span>{p.domain}</span>}
                                                      <span className="text-white/60">{p.severity}</span>
                                                      <span className="text-white/60 ml-auto">{p.count} events</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              )}
                                            </div>
                                          );
                                        }

                                        return null;
                                      })()}

                                      {/* Intelligence / Enriched Profile Panel */}
                                      {!enrichedProfiles[r.result_id] && loadingEnriched !== r.result_id && (
                                        <button
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            fetchEnrichedProfile(r.result_id);
                                          }}
                                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/15 text-violet-300 text-xs font-medium hover:bg-violet-500/25 transition-colors border border-violet-500/30"
                                        >
                                          <Sparkles className="w-3.5 h-3.5" />
                                          Analyse with AI Inference
                                        </button>
                                      )}
                                      {loadingEnriched === r.result_id && (
                                        <div className="text-violet-300/70 animate-pulse py-2 text-xs flex items-center gap-2">
                                          <Brain className="w-4 h-4 animate-pulse" />
                                          Running inference engine...
                                        </div>
                                      )}
                                      {enrichedProfiles[r.result_id] && !enrichedProfiles[r.result_id].error && (() => {
                                        const ep = enrichedProfiles[r.result_id];
                                        const enr = ep.enrichment;
                                        if (!enr) return null;

                                        return (
                                          <div className="space-y-3 border-t border-violet-500/20 pt-3 mt-2">
                                            <h4 className="text-violet-300 uppercase tracking-wider text-[10px] font-semibold flex items-center gap-1.5">
                                              <Brain className="w-3.5 h-3.5" />
                                              AI Inference
                                            </h4>

                                            {/* Dark Node enrichment */}
                                            {r.divergence_type === "dark_node" && (
                                              <div className="space-y-3">
                                                {/* Classification */}
                                                <div className="grid grid-cols-2 gap-2">
                                                  <div className="bg-violet-500/10 border border-violet-500/20 rounded-lg p-3">
                                                    <div className="flex items-center gap-1.5 text-white/60 text-[10px] uppercase mb-1.5">
                                                      <Cpu className="w-3 h-3" /> Inferred Type
                                                    </div>
                                                    <div className="text-white font-semibold text-sm">{enr.inferred_device_type}</div>
                                                    <div className="mt-1">
                                                      <ConfBadge value={enr.device_type_confidence} />
                                                    </div>
                                                  </div>
                                                  <div className="bg-violet-500/10 border border-violet-500/20 rounded-lg p-3">
                                                    <div className="flex items-center gap-1.5 text-white/60 text-[10px] uppercase mb-1.5">
                                                      <Network className="w-3 h-3" /> Inferred Role
                                                    </div>
                                                    <div className="text-white font-semibold text-sm">{enr.inferred_role}</div>
                                                    {enr.domain && <div className="text-white/60 text-xs mt-1">{enr.domain}</div>}
                                                  </div>
                                                </div>

                                                {/* Metadata hints */}
                                                <div className="flex flex-wrap gap-2">
                                                  {enr.vendor_hint && (
                                                    <span className="px-2 py-0.5 bg-white/5 rounded text-white/70 text-xs">Vendor: {enr.vendor_hint}</span>
                                                  )}
                                                  {enr.rat_type && (
                                                    <span className="px-2 py-0.5 bg-white/5 rounded text-white/70 text-xs">RAT: {enr.rat_type}</span>
                                                  )}
                                                  {enr.band && (
                                                    <span className="px-2 py-0.5 bg-white/5 rounded text-white/70 text-xs">Band: {enr.band}</span>
                                                  )}
                                                  {enr.site_association && (
                                                    <span className="px-2 py-0.5 bg-white/5 rounded text-white/70 text-xs">Site: {enr.site_association}</span>
                                                  )}
                                                </div>

                                                {/* Observation window */}
                                                {enr.observation_window && (
                                                  <div className="bg-white/5 rounded-lg p-3 text-xs space-y-0.5">
                                                    <div className="text-white/60 text-[10px] uppercase mb-1">Observation Window</div>
                                                    <div><span className="text-white/60">First seen: </span><span className="text-white/80">{enr.observation_window.first_seen?.split("T")[0] || "N/A"}</span></div>
                                                    <div><span className="text-white/60">Last seen: </span><span className="text-white/80">{enr.observation_window.last_seen?.split("T")[0] || "N/A"}</span></div>
                                                    <div><span className="text-white/60">Total samples: </span><span className="text-white">{enr.observation_window.total_samples?.toLocaleString()}</span></div>
                                                    <div><span className="text-white/60">Distinct KPIs: </span><span className="text-white">{enr.observation_window.distinct_kpis}</span></div>
                                                  </div>
                                                )}

                                                {/* Topology context */}
                                                {enr.topology_context?.neighbour_count > 0 && (
                                                  <div className="bg-white/5 rounded-lg p-3 text-xs space-y-1">
                                                    <div className="text-white/60 text-[10px] uppercase mb-1">
                                                      Topology Context ({enr.topology_context.neighbour_count} neighbours)
                                                    </div>
                                                    {enr.topology_context.neighbours.slice(0, 5).map((n: any, i: number) => (
                                                      <div key={i} className="flex gap-3 text-white/80">
                                                        <span className="font-mono">{n.peer_id}</span>
                                                        {n.neighbour_type && <span className="text-white/60">{n.neighbour_type}</span>}
                                                        {n.handover_attempts != null && <span className="text-white/60 ml-auto">{n.handover_attempts} HOs</span>}
                                                      </div>
                                                    ))}
                                                  </div>
                                                )}

                                                {/* Reasoning chain */}
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase">Reasoning</div>
                                                  {[...(enr.device_type_reasoning || []), ...(enr.role_reasoning || [])].map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-violet-400 shrink-0">--</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            )}

                                            {/* Phantom Node enrichment */}
                                            {r.divergence_type === "phantom_node" && (
                                              <div className="space-y-3">
                                                <div className="bg-white/5 rounded-lg p-3 text-xs space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase mb-1">Signal Absence Analysis</div>
                                                  {enr.signals_checked?.map((s: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-white/70">
                                                      <X className="w-3 h-3 text-red-400 shrink-0 mt-0.5" />
                                                      <span>No activity in <span className="font-mono text-white/80">{s}</span></span>
                                                    </div>
                                                  ))}
                                                </div>
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase">Reasoning</div>
                                                  {enr.reasoning?.map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-violet-400 shrink-0">--</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase flex items-center gap-1"><Wrench className="w-3 h-3" /> Remediation</div>
                                                  {enr.remediation_options?.map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-cyan-400 shrink-0">{i + 1}.</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            )}

                                            {/* Dark Edge enrichment */}
                                            {r.divergence_type === "dark_edge" && (
                                              <div className="space-y-3">
                                                <div className="bg-white/5 rounded-lg p-3 text-xs space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase mb-1">Relationship Analysis</div>
                                                  <div><span className="text-white/60">From: </span><span className="text-white">{enr.from_entity}</span></div>
                                                  <div><span className="text-white/60">To: </span><span className="text-white">{enr.to_entity}</span></div>
                                                  {enr.neighbour_type && <div><span className="text-white/60">Type: </span><span className="text-white font-mono">{enr.neighbour_type}</span></div>}
                                                  {enr.handover_attempts != null && <div><span className="text-white/60">Handover attempts: </span><span className="text-white">{enr.handover_attempts?.toLocaleString()}</span></div>}
                                                  {enr.handover_success_rate != null && <div><span className="text-white/60">Success rate: </span><span className="text-white">{(enr.handover_success_rate * 100).toFixed(1)}%</span></div>}
                                                </div>
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase">Reasoning</div>
                                                  {enr.reasoning?.map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-violet-400 shrink-0">--</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase flex items-center gap-1"><Wrench className="w-3 h-3" /> Remediation</div>
                                                  {enr.remediation_options?.map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-cyan-400 shrink-0">{i + 1}.</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            )}

                                            {/* Dark Attribute enrichment */}
                                            {r.divergence_type === "dark_attribute" && (
                                              <div className="space-y-3">
                                                <div className="bg-white/5 rounded-lg p-3 text-xs space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase mb-1">Attribute Discrepancy</div>
                                                  <div><span className="text-white/60">Attribute: </span><span className="text-white font-mono">{enr.attribute}</span></div>
                                                  <div><span className="text-white/60">CMDB value: </span><span className="text-red-400 line-through">{enr.cmdb_value}</span></div>
                                                  <div><span className="text-white/60">Observed: </span><span className="text-green-400">{enr.observed_value}</span></div>
                                                </div>
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase">Reasoning</div>
                                                  {enr.reasoning?.map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-violet-400 shrink-0">--</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase flex items-center gap-1"><Wrench className="w-3 h-3" /> Remediation</div>
                                                  {enr.remediation_options?.map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-cyan-400 shrink-0">{i + 1}.</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            )}

                                            {/* Phantom Edge / Identity Mutation enrichment */}
                                            {(r.divergence_type === "phantom_edge" || r.divergence_type === "identity_mutation") && (
                                              <div className="space-y-3">
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase">Reasoning</div>
                                                  {enr.reasoning?.map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-violet-400 shrink-0">--</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                                <div className="space-y-1">
                                                  <div className="text-white/60 text-[10px] uppercase flex items-center gap-1"><Wrench className="w-3 h-3" /> Remediation</div>
                                                  {enr.remediation_options?.map((r: string, i: number) => (
                                                    <div key={i} className="flex gap-2 text-xs text-white/70">
                                                      <span className="text-cyan-400 shrink-0">{i + 1}.</span>
                                                      <span>{r}</span>
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            )}

                                            {/* Confidence */}
                                            {enr.confidence != null && (
                                              <div className="flex items-center gap-2 pt-1">
                                                <span className="text-white/60 text-[10px] uppercase">Confidence:</span>
                                                <ConfBadge value={enr.confidence} />
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })()}

                                      {/* Topology link — for node-based types only */}
                                      {(r.divergence_type === "dark_node" || r.divergence_type === "phantom_node" || r.divergence_type === "identity_mutation") && (
                                        <a
                                          href={`/topology?entity_id=${encodeURIComponent(r.target_id)}`}
                                          onClick={(e) => {
                                            e.preventDefault();
                                            window.open(`/topology?entity_id=${encodeURIComponent(r.target_id)}`, "pedkai_workspace");
                                          }}
                                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-400/15 text-cyan-400 text-xs font-medium hover:bg-cyan-400/25 transition-colors"
                                        >
                                          <ExternalLink className="w-3.5 h-3.5" />
                                          Open in Topology
                                        </a>
                                      )}
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                      {records.length === 0 && (
                        <tr>
                          <td
                            colSpan={7}
                            className="px-4 py-8 text-center text-white/60"
                          >
                            No records found.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalRecords > PAGE_SIZE && (
                  <div className="p-4 border-t border-cyan-900/40 flex items-center justify-between text-xs text-white/80">
                    <span className="tabular-nums">
                      Page {page} of {Math.ceil(totalRecords / PAGE_SIZE).toLocaleString()}
                      <span className="text-white/70 ml-2">
                        ({((page - 1) * PAGE_SIZE + 1).toLocaleString()} - {Math.min(page * PAGE_SIZE, totalRecords).toLocaleString()} of {totalRecords.toLocaleString()})
                      </span>
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setPage(1)}
                        disabled={page === 1}
                        className="px-2 py-1 rounded bg-[#06203b] hover:bg-[#0d3b5e] text-slate-200 disabled:opacity-40"
                        title="First page"
                      >
                        <ChevronLeft className="w-3.5 h-3.5" />
                        <ChevronLeft className="w-3.5 h-3.5 -ml-2" />
                      </button>
                      <button
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                        disabled={page === 1}
                        className="px-3 py-1 rounded bg-[#06203b] hover:bg-[#0d3b5e] text-slate-200 disabled:opacity-40"
                      >
                        Prev
                      </button>
                      <button
                        onClick={() =>
                          setPage((p) =>
                            Math.min(Math.ceil(totalRecords / PAGE_SIZE), p + 1),
                          )
                        }
                        disabled={page >= Math.ceil(totalRecords / PAGE_SIZE)}
                        className="px-3 py-1 rounded bg-[#06203b] hover:bg-[#0d3b5e] text-slate-200 disabled:opacity-40"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Evaluation Section (collapsed) ──────────────────────── */}
            <div className="rounded-xl border border-violet-500/30 bg-violet-500/5 overflow-hidden">
              <button
                onClick={() => {
                  setShowEval(!showEval);
                  if (!showEval && !score) fetchScore();
                }}
                className="w-full p-4 flex items-center gap-2 text-sm font-medium text-violet-300 hover:text-violet-200 transition-colors"
              >
                <FlaskConical className="w-4 h-4" />
                <span>Evaluation: Score against ground-truth labels</span>
                <span className="text-xs text-violet-400 ml-2">
                  (Development / benchmarking only)
                </span>
                <span className="ml-auto text-violet-400">
                  {showEval ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                </span>
              </button>

              {showEval && (
                <div className="p-5 border-t border-violet-500/20 space-y-4">
                  {!score && (
                    <div className="flex justify-center py-8">
                      <RefreshCw className="w-6 h-6 text-violet-400 animate-spin" />
                    </div>
                  )}
                  {score?.error && (
                    <p className="text-sm text-violet-300">{score.error}</p>
                  )}
                  {score && !score.error && (
                    <>
                      <p className="text-xs text-white/80">
                        Comparing engine output against the pre-seeded{" "}
                        <code className="text-violet-300">divergence_manifest</code>{" "}
                        ({score.overall?.manifest_count?.toLocaleString()} labelled
                        divergences). This data is never used during detection.
                      </p>
                      <div className="flex gap-4 justify-center">
                        <ScoreBadge label="Recall" value={score.overall?.recall} />
                        <ScoreBadge label="Precision" value={score.overall?.precision} />
                        <ScoreBadge label="F1" value={score.overall?.f1} />
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-white/60 text-left border-b border-violet-500/20">
                              <th className="pb-1 pr-3">Type</th>
                              <th className="pb-1 pr-3 text-right">Labels</th>
                              <th className="pb-1 pr-3 text-right">Found</th>
                              <th className="pb-1 pr-3 text-right">Recall</th>
                              <th className="pb-1 text-right">F1</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(score.by_type ?? []).map((row: any) => {
                              const meta = TYPE_META[row.type];
                              return (
                                <tr key={row.type} className="border-b border-violet-500/10">
                                  <td className={`py-1 pr-3 font-medium ${meta?.colour ?? "text-white/80"}`}>
                                    {meta?.label ?? row.type}
                                  </td>
                                  <td className="py-1 pr-3 text-right text-white/80">
                                    {row.manifest_count?.toLocaleString()}
                                  </td>
                                  <td className="py-1 pr-3 text-right text-white/80">
                                    {row.engine_detected?.toLocaleString()}
                                  </td>
                                  <td className="py-1 pr-3 text-right">
                                    <span
                                      className={
                                        row.recall >= 0.8
                                          ? "text-green-400"
                                          : row.recall >= 0.5
                                            ? "text-amber-400"
                                            : "text-red-400"
                                      }
                                    >
                                      {Math.round(row.recall * 100)}%
                                    </span>
                                  </td>
                                  <td className="py-1 text-right">
                                    <span
                                      className={
                                        row.f1 >= 0.8
                                          ? "text-green-400"
                                          : row.f1 >= 0.5
                                            ? "text-amber-400"
                                            : "text-red-400"
                                      }
                                    >
                                      {Math.round(row.f1 * 100)}%
                                    </span>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
