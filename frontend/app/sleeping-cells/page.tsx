"use client";

import React, { useState, useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/app/context/AuthContext";
import { Loader2, AlertCircle, ChevronLeft, ChevronRight } from "lucide-react";

interface SleepingCell {
  cellId: string;
  site: string;
  domain: string;
  kpiDeviation: number;
  decayScore: number;
  lastSeen: string;
  status: "SLEEPING" | "RECOVERING" | "HEALTHY";
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

const PAGE_SIZE = 50;

type SortField = "cellId" | "kpiDeviation" | "decayScore" | "status";
type SortDir = "asc" | "desc";

export default function SleepingCellsPage() {
  const { token, authFetch } = useAuth();
  const [cells, setCells] = useState<SleepingCell[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [sortField, setSortField] = useState<SortField>("decayScore");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const fetchCells = async () => {
    if (!token) return;
    try {
      setLoading(true);
      setError(null);
      const res = await authFetch("/api/v1/sleeping-cells");
      if (res.ok) {
        const data = await res.json();
        setCells(data.cells ?? []);
        if (data.last_run) setLastRun(data.last_run);
      } else {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load sleeping cell data");
      setCells([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCells();
  }, [token]);

  const handleRunDetection = async () => {
    if (!token) return;
    setRunning(true);
    try {
      const res = await authFetch("/api/v1/sleeping-cells/detect", {
        method: "POST",
      });
      if (res.ok) {
        setLastRun(new Date().toISOString());
        await fetchCells();
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

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
    setPage(1);
  };

  // Derived stats (from all cells, not just current page)
  const monitored = cells.length;
  const activeSleeping = cells.filter((c) => c.status === "SLEEPING").length;
  const avgDecay =
    cells.length > 0
      ? cells.reduce((sum, c) => sum + c.decayScore, 0) / cells.length
      : 0;

  // Filter + sort (memoised to avoid recomputing on every render)
  const filtered = useMemo(() => {
    let list = statusFilter === "ALL" ? cells : cells.filter((c) => c.status === statusFilter);
    list = [...list].sort((a, b) => {
      let av: string | number = a[sortField];
      let bv: string | number = b[sortField];
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
            "px-5 py-2.5 rounded-lg text-sm font-bold transition-colors",
            running
              ? "bg-cyan-700 text-gray-950 cursor-not-allowed opacity-70"
              : "bg-cyan-400 hover:bg-cyan-300 text-gray-950",
          )}
        >
          {running ? "Running Detection..." : "Run Detection"}
        </button>
      </div>

      {lastRun && (
        <p className="text-white/60 text-xs">
          Last detection run: {new Date(lastRun).toLocaleString()}
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

      {/* Description panel */}
      <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-5">
        <h2 className="text-sm font-bold text-cyan-400 uppercase tracking-wider mb-2">
          What is a Sleeping Cell?
        </h2>
        <p className="text-white/80 text-sm leading-relaxed">
          A sleeping cell is a radio access node that is technically reachable and
          reports nominal alarm status, but has undergone progressive KPI
          degradation. Common causes include antenna misalignment, feeder
          attenuation, or software-level misconfiguration. The decay score
          (0-1) measures accumulated deviation from baseline; scores above{" "}
          <span className="text-amber-300 font-semibold">0.6</span> are flagged
          as actively sleeping.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
          <span className="ml-3 text-white/60">Loading sleeping cell data...</span>
        </div>
      ) : cells.length === 0 ? (
        <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-8 text-center">
          <p className="text-white/80 text-lg font-medium mb-2">No Data Available</p>
          <p className="text-white/60 text-sm max-w-md mx-auto">
            No sleeping cell detections found for this tenant. Run a detection cycle
            or ensure KPI telemetry has been ingested for cell-level entities.
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
              <p className="text-4xl font-bold text-white">{monitored.toLocaleString()}</p>
            </div>
            <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-5">
              <p className="text-xs font-semibold text-white/60 uppercase tracking-wider mb-1">
                Active Sleeping Cells
              </p>
              <p className="text-4xl font-bold text-amber-300">{activeSleeping.toLocaleString()}</p>
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
              <span className="text-xs text-white/60 uppercase tracking-wider">Filter:</span>
              {(["ALL", "SLEEPING", "RECOVERING", "HEALTHY"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => { setStatusFilter(s); setPage(1); }}
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
          <div className="bg-[#0a2d4a] rounded-lg border border-cyan-900/40 overflow-hidden">
            <table className="w-full">
              <thead className="bg-[#06203b] border-b border-cyan-900/40">
                <tr>
                  {(
                    [
                      { label: "Cell ID", field: "cellId" as SortField },
                      { label: "Site", field: null },
                      { label: "Domain", field: null },
                      { label: "KPI Deviation (%)", field: "kpiDeviation" as SortField },
                      { label: "Decay Score", field: "decayScore" as SortField },
                      { label: "Last Seen", field: null },
                      { label: "Status", field: "status" as SortField },
                    ] as { label: string; field: SortField | null }[]
                  ).map(({ label, field }) => (
                    <th
                      key={label}
                      onClick={field ? () => handleSort(field) : undefined}
                      className={cn(
                        "px-4 py-3 text-left text-xs font-semibold text-white/60 uppercase tracking-wider",
                        field && "cursor-pointer hover:text-white/90 select-none",
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
                    key={cell.cellId}
                    className="border-b border-cyan-900/20 hover:bg-white/5 transition-colors"
                  >
                    <td className="px-4 py-3 text-sm font-mono text-white font-medium">
                      {cell.cellId}
                    </td>
                    <td className="px-4 py-3 text-sm text-white/80">{cell.site}</td>
                    <td className="px-4 py-3 text-sm text-white/80">{cell.domain}</td>
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
                    <td className="px-4 py-3 text-xs text-white/60 font-mono">
                      {new Date(cell.lastSeen).toLocaleString()}
                    </td>
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
                  {Math.min(page * PAGE_SIZE, filtered.length).toLocaleString()} of{" "}
                  {filtered.length.toLocaleString()}
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
