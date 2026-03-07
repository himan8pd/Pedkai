"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  AlertTriangle,
  Eye,
  EyeOff,
  GitMerge,
  Layers,
  Link2,
  Link2Off,
  Play,
  RefreshCw,
  Shield,
  TrendingUp,
} from "lucide-react";
import { useAuth } from "@/app/context/AuthContext";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// ── Type colours ────────────────────────────────────────────────────────────
const TYPE_META: Record<
  string,
  { label: string; colour: string; colourBg: string; icon: React.ElementType }
> = {
  dark_node: {
    label: "Dark Nodes",
    colour: "text-red-400",
    colourBg: "bg-red-500/15 border-red-500/30",
    icon: Eye,
  },
  phantom_node: {
    label: "Phantom Nodes",
    colour: "text-amber-400",
    colourBg: "bg-amber-500/15 border-amber-500/30",
    icon: EyeOff,
  },
  identity_mutation: {
    label: "Identity Mutations",
    colour: "text-purple-400",
    colourBg: "bg-purple-500/15 border-purple-500/30",
    icon: GitMerge,
  },
  dark_attribute: {
    label: "Dark Attributes",
    colour: "text-blue-400",
    colourBg: "bg-blue-500/15 border-blue-500/30",
    icon: Layers,
  },
  dark_edge: {
    label: "Dark Edges",
    colour: "text-cyan-400",
    colourBg: "bg-cyan-500/15 border-cyan-500/30",
    icon: Link2,
  },
  phantom_edge: {
    label: "Phantom Edges",
    colour: "text-orange-400",
    colourBg: "bg-orange-500/15 border-orange-500/30",
    icon: Link2Off,
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

// ── API helpers ───────────────────────────────────────────────────────────
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

// ── Stat card ─────────────────────────────────────────────────────────────
function StatCard({
  label,
  value,
  sub,
  colour,
  colourBg,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  sub?: string;
  colour: string;
  colourBg: string;
  icon: React.ElementType;
}) {
  return (
    <div
      className={`rounded-xl border p-4 flex flex-col gap-1 ${colourBg}`}
    >
      <div className="flex items-center gap-2">
        <Icon className={`w-4 h-4 ${colour}`} />
        <span className="text-xs text-gray-400 uppercase tracking-wider font-semibold">
          {label}
        </span>
      </div>
      <span className={`text-2xl font-bold ${colour}`}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </span>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  );
}

// ── Score badge ───────────────────────────────────────────────────────────
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
    <div
      className={`flex flex-col items-center rounded-xl border px-5 py-3 ${colour}`}
    >
      <span className="text-2xl font-bold">{pct}%</span>
      <span className="text-xs opacity-75 mt-0.5">{label}</span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────
export default function DivergencePage() {
  const { tenantId, token } = useAuth();

  const [summary, setSummary] = useState<any>(null);
  const [score, setScore] = useState<any>(null);
  const [records, setRecords] = useState<any[]>([]);
  const [totalRecords, setTotalRecords] = useState(0);
  const [page, setPage] = useState(1);
  const [filterType, setFilterType] = useState<string>("");
  const [filterDomain, setFilterDomain] = useState<string>("");

  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const PAGE_SIZE = 25;

  // ── Fetch summary + score ──────────────────────────────────────────────
  const fetchSummaryAndScore = useCallback(async () => {
    if (!tenantId || !token) return;
    setError(null);
    try {
      const [s, sc] = await Promise.all([
        apiFetch(
          `/api/v1/reports/divergence/summary?tenant_id=${encodeURIComponent(tenantId)}`,
          token
        ),
        apiFetch(
          `/api/v1/reports/divergence/score/${encodeURIComponent(tenantId)}`,
          token
        ).catch(() => null),
      ]);
      setSummary(s);
      setScore(sc);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [tenantId, token]);

  // ── Fetch records page ─────────────────────────────────────────────────
  const fetchRecords = useCallback(async () => {
    if (!tenantId || !token) return;
    let path = `/api/v1/reports/divergence/records?tenant_id=${encodeURIComponent(tenantId)}&page=${page}&page_size=${PAGE_SIZE}`;
    if (filterType) path += `&divergence_type=${encodeURIComponent(filterType)}`;
    if (filterDomain) path += `&domain=${encodeURIComponent(filterDomain)}`;
    try {
      const data = await apiFetch(path, token);
      setRecords(data.records ?? []);
      setTotalRecords(data.total ?? 0);
    } catch {
      setRecords([]);
    }
  }, [tenantId, token, page, filterType, filterDomain]);

  useEffect(() => {
    fetchSummaryAndScore();
  }, [fetchSummaryAndScore]);

  useEffect(() => {
    if (summary) fetchRecords();
  }, [summary, fetchRecords]);

  // ── Run reconciliation ────────────────────────────────────────────────
  async function handleRun() {
    if (!tenantId || !token) return;
    setRunning(true);
    setRunError(null);
    try {
      await apiFetch(`/api/v1/reports/divergence/run`, token, {
        method: "POST",
        body: JSON.stringify({ tenant_id: tenantId }),
      });
      setLoading(true);
      setPage(1);
      setFilterType("");
      setFilterDomain("");
      await fetchSummaryAndScore();
    } catch (e: any) {
      setRunError(e.message);
    } finally {
      setRunning(false);
    }
  }

  // ── Domains ─────────────────────────────────────────────────────────
  const domains = summary
    ? Object.keys(summary.summary?.by_domain ?? {})
    : [];

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen text-white">
      <div className="max-w-screen-2xl mx-auto px-6 py-8 space-y-8">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Dark Graph Reconciliation
            </h1>
            <p className="mt-1 text-white/80 text-sm">
              CMDB intent vs ground truth reality — detecting divergences
              across entities, relationships, attributes, and identities.
            </p>
          </div>
          <button
            onClick={handleRun}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-400 hover:bg-cyan-300 disabled:opacity-50 transition-colors text-sm font-bold text-gray-950"
          >
            {running ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {running ? "Running…" : "Run Reconciliation"}
          </button>
        </div>

        {runError && (
          <div className="p-3 rounded-lg bg-red-900/40 border border-red-700 text-red-300 text-sm">
            {runError}
          </div>
        )}

        {/* No run yet */}
        {!loading && error && (
          <div className="flex flex-col items-center justify-center py-32 text-center space-y-4">
            <AlertTriangle className="w-12 h-12 text-amber-400" />
            <p className="text-gray-400 text-lg">No reconciliation run found.</p>
            <p className="text-gray-500 text-sm">
              Click <strong className="text-white">Run Reconciliation</strong> to compare
              the CMDB against ground truth and discover divergences.
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
            {/* Run metadata bar */}
            <div className="flex items-center gap-4 text-xs text-white/70">
              <span>
                Run:{" "}
                <span className="font-mono text-white">
                  {summary.run_id?.slice(0, 8)}
                </span>
              </span>
              {summary.run_at && (
                <span>
                  Completed:{" "}
                  {new Date(summary.run_at).toLocaleString("en-GB")}
                </span>
              )}
              {summary.duration_seconds != null && (
                <span>Duration: {summary.duration_seconds}s</span>
              )}
            </div>

            {/* Type stat cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
              {TYPE_ORDER.map((t) => {
                const meta = TYPE_META[t];
                const count = summary.summary?.by_type?.[t] ?? 0;
                return (
                  <StatCard
                    key={t}
                    label={meta.label}
                    value={count}
                    colour={meta.colour}
                    colourBg={meta.colourBg}
                    icon={meta.icon}
                  />
                );
              })}
            </div>

            {/* CMDB accuracy + scoring */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* CMDB accuracy */}
              <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-4">
                <div className="flex items-center gap-2">
                  <Shield className="w-5 h-5 text-blue-400" />
                  <h2 className="font-semibold text-white">CMDB Accuracy</h2>
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  {[
                    [
                      "Entity coverage",
                      `${summary.cmdb_accuracy?.entity_accuracy_pct?.toFixed(1)}%`,
                      "CMDB entities / Ground truth",
                    ],
                    [
                      "Edge coverage",
                      `${summary.cmdb_accuracy?.edge_accuracy_pct?.toFixed(1)}%`,
                      "CMDB edges / Ground truth",
                    ],
                    [
                      "CMDB entities",
                      summary.cmdb_accuracy?.entity_count_cmdb?.toLocaleString(),
                      "Declared",
                    ],
                    [
                      "Reality entities",
                      summary.cmdb_accuracy?.entity_count_reality?.toLocaleString(),
                      "Ground truth",
                    ],
                    [
                      "CMDB edges",
                      summary.cmdb_accuracy?.edge_count_cmdb?.toLocaleString(),
                      "Declared",
                    ],
                    [
                      "Reality edges",
                      summary.cmdb_accuracy?.edge_count_reality?.toLocaleString(),
                      "Ground truth",
                    ],
                  ].map(([lbl, val, sub]) => (
                    <div key={lbl} className="bg-white/5 rounded-lg p-3">
                      <div className="text-slate-400 text-xs">{lbl}</div>
                      <div className="text-white font-bold mt-0.5">{val}</div>
                      <div className="text-slate-400 text-xs">{sub}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Detection score vs manifest */}
              {score && (
                <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-4">
                  <div className="flex items-center gap-2">
                    <TrendingUp className="w-5 h-5 text-green-400" />
                    <h2 className="font-semibold text-white">
                      Detection Score vs Ground Truth Labels
                    </h2>
                  </div>
                  <p className="text-xs text-white/80">
                    Scoring engine findings against the pre-seeded{" "}
                    <code className="text-gray-400">divergence_manifest</code>{" "}
                    ({score.overall?.manifest_count?.toLocaleString()} labelled
                    ground truth divergences).
                  </p>
                  <div className="flex gap-4 justify-center">
                    <ScoreBadge
                      label="Recall"
                      value={score.overall?.recall}
                    />
                    <ScoreBadge
                      label="Precision"
                      value={score.overall?.precision}
                    />
                    <ScoreBadge label="F1" value={score.overall?.f1} />
                  </div>
                  {/* Per-type scoring table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-slate-400 text-left border-b border-cyan-900/30">
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
                            <tr
                              key={row.type}
                              className="border-b border-cyan-900/20"
                            >
                              <td
                                className={`py-1 pr-3 font-medium ${meta?.colour ?? "text-gray-300"}`}
                              >
                                {meta?.label ?? row.type}
                              </td>
                              <td className="py-1 pr-3 text-right text-slate-300">
                                {row.manifest_count?.toLocaleString()}
                              </td>
                              <td className="py-1 pr-3 text-right text-gray-300">
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
                </div>
              )}
            </div>

            {/* Domain breakdown bar */}
            {domains.length > 0 && (
              <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5 space-y-3">
                <h2 className="font-semibold text-white text-sm">
                  Divergences by Domain
                </h2>
                <div className="space-y-2">
                  {domains.map((d) => {
                    const cnt = summary.summary.by_domain[d];
                    const total = summary.summary.total_divergences || 1;
                    const pct = Math.round((cnt / total) * 100);
                    return (
                      <div key={d} className="flex items-center gap-3 text-sm">
                        <span className="w-32 text-right text-white text-xs shrink-0">
                          {DOMAIN_LABELS[d] ?? d}
                        </span>
                        <div className="flex-1 bg-[#06203b] rounded-full h-2 overflow-hidden">
                          <div
                            className="h-2 rounded-full bg-gradient-to-r from-cyan-400 to-violet-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="w-20 text-white text-xs">
                          {cnt.toLocaleString()}{" "}
                          <span className="text-white/60">({pct}%)</span>
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Records table */}
            <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] overflow-hidden">
              {/* Filters */}
              <div className="p-4 border-b border-cyan-900/40 flex flex-wrap gap-3 items-center">
                <span className="text-sm text-white font-medium">
                  {totalRecords.toLocaleString()} divergences
                </span>
                <div className="flex gap-2 flex-wrap ml-auto">
                  {/* Type filter */}
                  <select
                    value={filterType}
                    onChange={(e) => {
                      setFilterType(e.target.value);
                      setPage(1);
                    }}
                    className="text-xs px-3 py-1.5 rounded-lg bg-[#06203b] border border-cyan-900/50 text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                  >
                    <option value="">All types</option>
                    {TYPE_ORDER.map((t) => (
                      <option key={t} value={t}>
                        {TYPE_META[t].label}
                      </option>
                    ))}
                  </select>
                  {/* Domain filter */}
                  <select
                    value={filterDomain}
                    onChange={(e) => {
                      setFilterDomain(e.target.value);
                      setPage(1);
                    }}
                    className="text-xs px-3 py-1.5 rounded-lg bg-[#06203b] border border-cyan-900/50 text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                  >
                    <option value="">All domains</option>
                    {domains.map((d) => (
                      <option key={d} value={d}>
                        {DOMAIN_LABELS[d] ?? d}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-cyan-900/40 text-xs text-slate-400 uppercase tracking-wider">
                    <tr>
                      <th className="text-left px-4 py-2">Type</th>
                      <th className="text-left px-4 py-2">Entity/Rel Type</th>
                      <th className="text-left px-4 py-2">Domain</th>
                      <th className="text-left px-4 py-2 max-w-xs">
                        Description
                      </th>
                      <th className="text-left px-4 py-2">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((r) => {
                      const meta = TYPE_META[r.divergence_type];
                      const Icon = meta?.icon ?? AlertTriangle;
                      return (
                        <tr
                          key={r.result_id}
                          className="border-b border-cyan-900/20 hover:bg-white/5 transition-colors"
                        >
                          <td className="px-4 py-2 whitespace-nowrap">
                            <span
                              className={`inline-flex items-center gap-1.5 text-xs font-medium ${meta?.colour ?? "text-gray-400"}`}
                            >
                              <Icon className="w-3.5 h-3.5" />
                              {meta?.label ?? r.divergence_type}
                            </span>
                          </td>
                          <td className="px-4 py-2 text-white text-xs font-mono">
                            {r.target_type ?? "—"}
                          </td>
                          <td className="px-4 py-2 text-slate-400 text-xs">
                            {DOMAIN_LABELS[r.domain] ?? r.domain ?? "—"}
                          </td>
                          <td className="px-4 py-2 text-white text-xs max-w-xs truncate">
                            {r.description}
                          </td>
                          <td className="px-4 py-2 text-xs text-slate-300 font-mono">
                            {r.attribute_name && (
                              <span>
                                <span className="text-gray-400">
                                  {r.attribute_name}
                                </span>
                                {": "}
                                <span className="text-red-400 line-through">
                                  {r.cmdb_value}
                                </span>{" "}
                                →{" "}
                                <span className="text-green-400">
                                  {r.ground_truth_value}
                                </span>
                              </span>
                            )}
                            {r.cmdb_external_id && (
                              <span>
                                <span className="text-red-400 line-through">
                                  {r.cmdb_external_id?.slice(0, 30)}
                                </span>{" "}
                                →{" "}
                                <span className="text-green-400">
                                  {r.gt_external_id?.slice(0, 30)}
                                </span>
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {records.length === 0 && (
                      <tr>
                        <td
                          colSpan={5}
                          className="px-4 py-8 text-center text-white"
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
                  <span>
                    Page {page} of {Math.ceil(totalRecords / PAGE_SIZE)}
                  </span>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="px-3 py-1 rounded bg-[#06203b] hover:bg-[#0d3b5e] text-slate-200 disabled:opacity-40"
                    >
                      ← Prev
                    </button>
                    <button
                      onClick={() =>
                        setPage((p) =>
                          Math.min(Math.ceil(totalRecords / PAGE_SIZE), p + 1)
                        )
                      }
                      disabled={page >= Math.ceil(totalRecords / PAGE_SIZE)}
                      className="px-3 py-1 rounded bg-[#06203b] hover:bg-[#0d3b5e] text-slate-200 disabled:opacity-40"
                    >
                      Next →
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
