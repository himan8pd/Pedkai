"use client";

import React, { useState, useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import * as Cache from "@/app/apiCache";
import { useAuth } from "@/app/context/AuthContext";
import {
  Loader2,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  RefreshCw,
  Calendar,
} from "lucide-react";

interface SleepingCell {
  cellId: string;
  site: string;
  domain: string;
  kpiDeviation: number;
  decayScore: number;
  lastSeen: string;
  status: "SLEEPING" | "RECOVERING" | "HEALTHY";
  entityName?: string;
  entityType?: string;
  baselineMean?: number;
  currentValue?: number;
  metricName?: string;
}

interface SleepingCellsData {
  cells: SleepingCell[];
  last_run: string | null;
  reference_time: string | null;
}

function statusBadge(status: SleepingCell["status"]) {
  switch (status) {
    case "SLEEPING":
      return "bg-amber-900/50 text-amber-300 border border-amber-700/60";
    case "RECOVERING":
      return "bg-cyan-900/50 text-cyan-300 border border-cyan-700/60";
    case "HEALTHY":
      return "bg-emerald-900/50 text-emerald-300 border border-emerald-700/60";
  }
}

/** Mini bar comparing current vs baseline. */
function BaselineBar({
  current,
  baseline,
}: {
  current?: number;
  baseline?: number;
}) {
  if (current == null || baseline == null || baseline === 0) {
    return <span className="text-white/30 text-xs">—</span>;
  }
  const ratio = Math.min(2, Math.max(0, current / baseline));
  const pct = Math.round(ratio * 50); // scale to 50% = healthy
  const isLow = current < baseline * 0.8;
  return (
    <div className="flex flex-col gap-0.5 min-w-[80px]">
      <div className="flex items-center gap-1 text-xs">
        <span className={isLow ? "text-red-400 font-semibold" : "text-emerald-400"}>
          {current.toFixed(1)}
        </span>
        <span className="text-white/40">/</span>
        <span className="text-white/60">{baseline.toFixed(1)}</span>
      </div>
      <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            isLow ? "bg-red-500" : "bg-emerald-500",
          )}
          style={{ width: `${Math.min(100, pct * 2)}%` }}
        />
      </div>
    </div>
  );
}

const PAGE_SIZE = 50;
type SortField = "site" | "kpiDeviation" | "decayScore" | "status" | "entityType";
type SortDir = "asc" | "desc";

function cacheKey(tenantId: string, refTime: string) {
  return `sleeping-cells:${tenantId}:${refTime || "auto"}`;
}

export default function SleepingCellsPage() {
  const { token, tenantId, authFetch } = useAuth();

  const [data, setData] = useState<SleepingCellsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  // Time seed: empty = auto (use backend's max KPI timestamp)
  const [timeSeed, setTimeSeed] = useState<string>("");
  const [autoRefTime, setAutoRefTime] = useState<string>("");

  // Table controls
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [sortField, setSortField] = useState<SortField>("decayScore");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // On mount: fetch auto reference time to pre-populate the picker
  useEffect(() => {
    if (!token) return;
    authFetch("/api/v1/sleeping-cells/reference-time")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.reference_time) {
          // Convert to YYYY-MM-DDTHH:mm (datetime-local input format)
          const iso = d.reference_time.slice(0, 16);
          setAutoRefTime(iso);
          // If user hasn't set a manual seed, default to the auto one
          setTimeSeed((prev) => prev || iso);
        }
      })
      .catch(() => {});
  }, [token]);

  const fetchCells = async (refTime: string = timeSeed) => {
    if (!token) return;
    const ck = cacheKey(tenantId, refTime);
    const cached = Cache.get<SleepingCellsData>(ck, Cache.TTL.MEDIUM);
    if (cached) {
      setData(cached);
      setLoading(false);
      // Still refresh in background if stale (>2 min)
      const age = Cache.ageSeconds(ck) ?? 0;
      if (age < 120) return;
    }

    try {
      setError(null);
      const params = refTime ? `?reference_time=${encodeURIComponent(refTime)}` : "";
      const res = await authFetch(`/api/v1/sleeping-cells${params}`);
      if (res.ok) {
        const d: SleepingCellsData = await res.json();
        Cache.set(ck, d);
        setData(d);
      } else {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load sleeping cell data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token || !timeSeed) return;
    setLoading(!Cache.get(cacheKey(tenantId, timeSeed), Cache.TTL.MEDIUM));
    fetchCells(timeSeed);
  }, [token, timeSeed]);

  const handleRunDetection = async () => {
    if (!token) return;
    setRunning(true);
    try {
      const params = timeSeed
        ? `?reference_time=${encodeURIComponent(timeSeed)}`
        : "";
      const res = await authFetch(`/api/v1/sleeping-cells/detect${params}`, {
        method: "POST",
      });
      if (res.ok) {
        const d: SleepingCellsData = await res.json();
        // If scan returned data immediately (cache was warm), use it
        if (d.cells.length > 0) {
          Cache.set(cacheKey(tenantId, timeSeed), d);
          setData(d);
        } else {
          // Cold cache — backend is running scan; poll GET every 5s
          startPolling();
        }
      } else {
        const body = await res.json().catch(() => null);
        setError(body?.detail || `Detection failed (HTTP ${res.status})`);
      }
    } catch (err: any) {
      setError(err.message || "Detection request failed");
    } finally {
      setRunning(false);
    }
  };

  const startPolling = () => {
    if (pollRef.current) clearTimeout(pollRef.current);
    const poll = async (attempts: number) => {
      await fetchCells(timeSeed);
      if (
        (!data || data.cells.length === 0) &&
        attempts < 12 // up to 60s
      ) {
        pollRef.current = setTimeout(() => poll(attempts + 1), 5000);
      }
    };
    pollRef.current = setTimeout(() => poll(0), 5000);
  };

  useEffect(() => () => { if (pollRef.current) clearTimeout(pollRef.current); }, []);

  const handleSort = (field: SortField) => {
    setSortField((f) => {
      setSortDir(f === field ? (sortDir === "asc" ? "desc" : "asc") : "desc");
      return field;
    });
    setPage(1);
  };

  const cells = data?.cells ?? [];

  const monitored = cells.length;
  const activeSleeping = cells.filter((c) => c.status === "SLEEPING").length;
  const avgDecay =
    cells.length > 0
      ? cells.reduce((sum, c) => sum + c.decayScore, 0) / cells.length
      : 0;

  const filtered = useMemo(() => {
    let list =
      statusFilter === "ALL" ? cells : cells.filter((c) => c.status === statusFilter);
    list = [...list].sort((a, b) => {
      let av: string | number = a[sortField] ?? "";
      let bv: string | number = b[sortField] ?? "";
      if (typeof av === "string") av = av.toLowerCase();
      if (typeof bv === "string") bv = bv.toLowerCase();
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return list;
  }, [cells, statusFilter, sortField, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageCells = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const SortIndicator = ({ field }: { field: SortField }) =>
    sortField === field ? (
      <span className="ml-1 text-cyan-400">{sortDir === "asc" ? "↑" : "↓"}</span>
    ) : null;

  return (
    <div className="space-y-6 p-4 md:p-8">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white mb-1">
            Sleeping Cell Monitor
          </h1>
          <p className="text-white/80">
            Detects cells that appear operationally active but exhibit degraded
            KPI profiles — indicating silent performance decay.
          </p>
        </div>
        <button
          onClick={handleRunDetection}
          disabled={running}
          className={cn(
            "flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-bold transition-colors",
            running
              ? "bg-cyan-700 text-gray-950 cursor-not-allowed opacity-70"
              : "bg-cyan-400 hover:bg-cyan-300 text-gray-950",
          )}
        >
          {running ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Running…</>
          ) : (
            <><RefreshCw className="w-4 h-4" /> Run Detection</>
          )}
        </button>
      </div>

      {/* Time seed control */}
      <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg px-5 py-4 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2 text-sm text-white/70">
          <Calendar className="w-4 h-4 text-cyan-400" />
          <span className="font-semibold text-white/90">Analysis reference time:</span>
        </div>
        <input
          type="datetime-local"
          value={timeSeed}
          onChange={(e) => {
            setTimeSeed(e.target.value);
            setPage(1);
          }}
          className="bg-[#06203b] border border-cyan-900/50 rounded px-3 py-1.5 text-sm text-white/90 focus:outline-none focus:border-cyan-500"
        />
        {autoRefTime && timeSeed !== autoRefTime && (
          <button
            onClick={() => setTimeSeed(autoRefTime)}
            className="text-xs text-cyan-400 hover:text-cyan-300 underline underline-offset-2"
          >
            Reset to latest data ({autoRefTime.slice(0, 10)})
          </button>
        )}
        <p className="text-xs text-white/50 ml-auto">
          Detector looks back 7 days from this point. Change date to analyse a
          different slice of your historical KPI data.
        </p>
      </div>

      {data?.last_run && (
        <p className="text-white/60 text-xs">
          Last scan: {new Date(data.last_run).toLocaleString()}
          {data.reference_time && (
            <span className="ml-2 text-white/40">
              · ref {new Date(data.reference_time).toLocaleDateString()}
            </span>
          )}
        </p>
      )}

      {error && (
        <div className="bg-amber-900/30 border border-amber-700/40 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-amber-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm text-amber-200 font-medium">Detection Unavailable</p>
            <p className="text-xs text-amber-300/70 mt-1">{error}</p>
          </div>
        </div>
      )}

      {/* What is a sleeping cell */}
      <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-5">
        <h2 className="text-sm font-bold text-cyan-400 uppercase tracking-wider mb-2">
          What is a Sleeping Cell?
        </h2>
        <p className="text-white/80 text-sm leading-relaxed">
          A sleeping cell is technically reachable and reports nominal alarm
          status, but has undergone progressive KPI degradation. The{" "}
          <span className="text-white font-semibold">Current / Baseline</span>{" "}
          column shows the latest observed KPI vs its 7-day healthy average —
          making it easy to see how far a cell has drifted. Decay scores above{" "}
          <span className="text-amber-300 font-semibold">0.6</span> are flagged
          as actively sleeping.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
          <span className="ml-3 text-white/60">Loading sleeping cell data…</span>
        </div>
      ) : cells.length === 0 ? (
        <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-8 text-center">
          <p className="text-white/80 text-lg font-medium mb-2">No Data Available</p>
          <p className="text-white/60 text-sm max-w-md mx-auto">
            No detections for the selected time window. Click{" "}
            <strong>Run Detection</strong> to trigger a scan, or adjust the
            reference time above.
          </p>
        </div>
      ) : (
        <>
          {/* KPI stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-5">
              <p className="text-xs font-semibold text-white/60 uppercase tracking-wider mb-1">
                Cells Monitored
              </p>
              <p className="text-4xl font-bold text-white">
                {monitored.toLocaleString()}
              </p>
            </div>
            <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-5">
              <p className="text-xs font-semibold text-white/60 uppercase tracking-wider mb-1">
                Active Sleeping Cells
              </p>
              <p className="text-4xl font-bold text-amber-300">
                {activeSleeping.toLocaleString()}
              </p>
            </div>
            <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-5">
              <p className="text-xs font-semibold text-white/60 uppercase tracking-wider mb-1">
                Avg Decay Score
              </p>
              <p className="text-4xl font-bold text-cyan-400">
                {avgDecay.toFixed(2)}
              </p>
            </div>
          </div>

          {/* Filter + pagination controls */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xs text-white/60 uppercase tracking-wider">
                Filter:
              </span>
              {(["ALL", "SLEEPING", "RECOVERING", "HEALTHY"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => {
                    setStatusFilter(s);
                    setPage(1);
                  }}
                  className={cn(
                    "px-3 py-1 rounded text-xs font-bold transition-colors border",
                    statusFilter === s
                      ? s === "SLEEPING"
                        ? "bg-amber-900/60 text-amber-300 border-amber-700"
                        : s === "RECOVERING"
                          ? "bg-cyan-900/60 text-cyan-300 border-cyan-700"
                          : s === "HEALTHY"
                            ? "bg-emerald-900/60 text-emerald-300 border-emerald-700"
                            : "bg-white/10 text-white border-white/30"
                      : "bg-transparent text-white/50 border-white/15 hover:border-white/30 hover:text-white/80",
                  )}
                >
                  {s === "ALL" ? `All (${monitored.toLocaleString()})` : s}
                </button>
              ))}
            </div>
            <p className="text-xs text-white/60">
              {filtered.length.toLocaleString()} cells · page {page} of {totalPages}
            </p>
          </div>

          {/* Table */}
          <div className="bg-[#0a2d4a] rounded-lg border border-cyan-900/40 overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead className="bg-[#06203b] border-b border-cyan-900/40">
                <tr>
                  {(
                    [
                      { label: "Entity", field: "site" as SortField },
                      { label: "Type", field: "entityType" as SortField },
                      { label: "KPI", field: null },
                      { label: "Current / Baseline", field: null },
                      { label: "KPI Dev %", field: "kpiDeviation" as SortField },
                      { label: "Decay", field: "decayScore" as SortField },
                      { label: "Status", field: "status" as SortField },
                      { label: "", field: null },
                    ] as { label: string; field: SortField | null }[]
                  ).map(({ label, field }, i) => (
                    <th
                      key={i}
                      onClick={field ? () => handleSort(field) : undefined}
                      className={cn(
                        "px-4 py-3 text-left text-xs font-semibold text-white/60 uppercase tracking-wider whitespace-nowrap",
                        field &&
                          "cursor-pointer hover:text-white/90 select-none",
                      )}
                    >
                      {label}
                      {field && <SortIndicator field={field} />}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageCells.map((cell) => (
                  <tr
                    key={`${cell.cellId}-${cell.domain}`}
                    className="border-b border-cyan-900/20 hover:bg-white/5 transition-colors"
                  >
                    {/* Entity name — human-readable if available */}
                    <td className="px-4 py-3 text-sm font-mono text-white font-medium max-w-[180px]">
                      <span title={cell.cellId}>{cell.site}</span>
                    </td>
                    {/* Entity type */}
                    <td className="px-4 py-3 text-xs text-white/60 font-mono">
                      {cell.entityType ?? "—"}
                    </td>
                    {/* KPI metric name */}
                    <td className="px-4 py-3 text-xs text-white/70">
                      {cell.metricName ?? cell.domain}
                    </td>
                    {/* Current vs Baseline mini-bar */}
                    <td className="px-4 py-3">
                      <BaselineBar
                        current={cell.currentValue}
                        baseline={cell.baselineMean}
                      />
                    </td>
                    {/* KPI deviation % */}
                    <td className="px-4 py-3 text-sm">
                      <span
                        className={cn(
                          "font-semibold",
                          cell.kpiDeviation < -20
                            ? "text-red-400"
                            : cell.kpiDeviation < -10
                              ? "text-amber-300"
                              : "text-emerald-400",
                        )}
                      >
                        {cell.kpiDeviation.toFixed(1)}%
                      </span>
                    </td>
                    {/* Decay score */}
                    <td className="px-4 py-3 text-sm">
                      <span
                        className={cn(
                          "font-semibold font-mono",
                          cell.decayScore >= 0.6
                            ? "text-amber-300"
                            : cell.decayScore >= 0.3
                              ? "text-yellow-400"
                              : "text-emerald-400",
                        )}
                      >
                        {cell.decayScore.toFixed(2)}
                      </span>
                    </td>
                    {/* Status badge */}
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "px-2.5 py-1 rounded-full text-xs font-bold uppercase",
                          statusBadge(cell.status),
                        )}
                      >
                        {cell.status}
                      </span>
                    </td>
                    {/* Topology link — only shown when entity name is available */}
                    <td className="px-4 py-3">
                      {cell.entityName && (
                        <Link
                          href={`/topology?seed=${encodeURIComponent(cell.entityName)}`}
                          className="text-cyan-400 hover:text-cyan-300 transition-colors"
                          title={`Explore ${cell.entityName} in Topology`}
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Pagination footer */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-cyan-900/40 bg-[#06203b]">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-semibold text-white/70 border border-white/15 hover:border-white/30 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-3.5 h-3.5" /> Prev
                </button>
                <span className="text-xs text-white/50">
                  {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–
                  {Math.min(page * PAGE_SIZE, filtered.length).toLocaleString()}{" "}
                  of {filtered.length.toLocaleString()}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-semibold text-white/70 border border-white/15 hover:border-white/30 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  Next <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
