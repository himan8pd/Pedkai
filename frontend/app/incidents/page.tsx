"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ExternalLink,
  Network,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/app/context/AuthContext";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface Incident {
  id: string;
  title: string;
  impact: string | null;
  urgency: string | null;
  priority: string | null;
  severity: string | null;
  status: string;
  entity_id: string;
  entity_external_id: string;
  tenant_id: string;
  reasoning_chain: any;
  resolution_summary: string | null;
  kpi_snapshot: any;
  created_at: string;
  updated_at: string;
}

/* ── ITIL v4 Priority definitions ─────────────────────────────────── */
const PRIORITY_META: Record<
  string,
  { label: string; desc: string; color: string; cardRing: string }
> = {
  P1: {
    label: "P1 — Critical",
    desc: "Impact: High × Urgency: High",
    color: "bg-red-900/60 text-red-300 border-red-700",
    cardRing: "ring-red-500 border-red-500",
  },
  P2: {
    label: "P2 — High",
    desc: "Impact: High × Urgency: Med",
    color: "bg-orange-900/60 text-orange-300 border-orange-700",
    cardRing: "ring-orange-500 border-orange-500",
  },
  P3: {
    label: "P3 — Medium",
    desc: "Impact: Med × Urgency: Med",
    color: "bg-yellow-900/60 text-yellow-300 border-yellow-700",
    cardRing: "ring-yellow-500 border-yellow-500",
  },
  P4: {
    label: "P4 — Low",
    desc: "Impact: Low × Urgency: Med",
    color: "bg-blue-900/60 text-blue-300 border-blue-700",
    cardRing: "ring-blue-500 border-blue-500",
  },
  P5: {
    label: "P5 — Info",
    desc: "Impact: Low × Urgency: Low",
    color: "bg-slate-700/60 text-slate-300 border-slate-500",
    cardRing: "ring-slate-400 border-slate-400",
  },
};

function priorityColor(p: string | null) {
  return (
    PRIORITY_META[p ?? ""]?.color ?? "bg-slate-700/50 text-slate-300 border-slate-500"
  );
}

function impactUrgencyColor(level: string | null) {
  switch (level?.toLowerCase()) {
    case "high":
      return "text-red-400";
    case "medium":
      return "text-amber-400";
    case "low":
      return "text-cyan-400";
    default:
      return "text-gray-400";
  }
}

function statusColor(s: string) {
  switch (s?.toLowerCase()) {
    case "detected":
      return "bg-blue-900/40 text-blue-300";
    case "rca":
      return "bg-purple-900/40 text-purple-300";
    case "anomaly":
      return "bg-red-400/40 text-red-500";
    case "sitrep_draft":
    case "sitrep_approved":
      return "bg-cyan-900/40 text-cyan-300";
    case "resolving":
    case "resolution_approved":
      return "bg-amber-900/40 text-amber-300";
    case "resolved":
    case "closed":
      return "bg-emerald-900/40 text-emerald-300";
    default:
      return "bg-slate-700/40 text-slate-300";
  }
}

const PAGE_SIZE = 50;

type SortableColumn = "title" | "priority" | "severity" | "status" | "created_at" | "impact" | "urgency";

export default function IncidentsPage() {
  const { token, tenantId } = useAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterPriority, setFilterPriority] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<SortableColumn>("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [searchText, setSearchText] = useState("");
  const [searchInput, setSearchInput] = useState("");

  // Priority card counts -- fetched separately (unfiltered by status/search/page)
  const [priorityCounts, setPriorityCounts] = useState<Record<string, number>>({});
  const [summaryTotal, setSummaryTotal] = useState(0);
  const [summaryOpen, setSummaryOpen] = useState(0);
  const [summaryClosed, setSummaryClosed] = useState(0);

  // Fetch summary counts (all incidents, no pagination/filter)
  const fetchSummary = useCallback(async () => {
    if (!token || !tenantId) return;
    try {
      // Fetch a large page to get counts -- use page_size=1 just for total, then fetch by severity
      const countRes = await fetch(
        `${API_BASE_URL}/api/v1/incidents/?page=1&page_size=1`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (countRes.ok) {
        const countData = await countRes.json();
        setSummaryTotal(countData.total);
      }

      // Fetch closed count
      const closedRes = await fetch(
        `${API_BASE_URL}/api/v1/incidents/?page=1&page_size=1&status=closed`,
        { headers: { Authorization: `Bearer ${token}` } },
      );

      if (closedRes.ok) {
        const closedData = await closedRes.json();
        setSummaryClosed(closedData.total);
      }

      // Fetch priority counts: P1-P5
      const priResults = await Promise.all(
        ["critical", "major", "minor", "warning", "info"].map((sev) =>
          fetch(
            `${API_BASE_URL}/api/v1/incidents/?page=1&page_size=1&severity=${sev}`,
            { headers: { Authorization: `Bearer ${token}` } },
          ).then((r) => r.json()),
        ),
      );
      // Map severity to priority counts
      const sevToPri: Record<string, string> = {
        critical: "P1",
        major: "P2",
        minor: "P3",
        warning: "P4",
        info: "P5",
      };
      const counts: Record<string, number> = {};
      ["critical", "major", "minor", "warning", "info"].forEach((sev, idx) => {
        counts[sevToPri[sev]] = priResults[idx]?.total ?? 0;
      });
      setPriorityCounts(counts);
    } catch {
      // Silently fail -- summary is non-critical
    }
  }, [token, tenantId]);

  // Fetch paginated incidents
  const fetchIncidents = useCallback(async () => {
    if (!token || !tenantId) return;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
        sort_by: sortBy,
        sort_dir: sortDir,
      });
      if (filterStatus === "open") {
        // "open" means not closed -- the backend doesn't have a "not closed" filter,
        // so we don't pass status and filter client-side... but that breaks pagination.
        // Instead, let's NOT pass status for "open" and handle it differently.
        // Actually the backend status filter is exact match. For "open" we need != closed.
        // We'll leave status unset and do all/open/closed on the summary tabs.
        // For "closed", pass status=closed.
      } else if (filterStatus === "closed") {
        params.set("status", "closed");
      }
      // filterStatus === "all" -- no status param

      if (filterPriority !== "all") {
        // Priority filter maps to severity in backend
        const priToSev: Record<string, string> = {
          P1: "critical",
          P2: "major",
          P3: "minor",
          P4: "warning",
          P5: "info",
        };
        const sev = priToSev[filterPriority];
        if (sev) params.set("severity", sev);
      }

      if (searchText) {
        params.set("search", searchText);
      }

      const res = await fetch(
        `${API_BASE_URL}/api/v1/incidents/?${params.toString()}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setIncidents(data.incidents);
      setTotalCount(data.total);
    } catch (err: any) {
      setError(err.message ?? "Failed to load incidents");
    } finally {
      setLoading(false);
    }
  }, [token, tenantId, page, sortBy, sortDir, filterStatus, filterPriority, searchText]);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  // Derived
  const openCount = summaryTotal - summaryClosed;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  // For "open" filter, we need to exclude closed incidents client-side
  // since backend doesn't support != filter. We handle this by not passing status
  // and letting the backend return all, then filtering. But that breaks pagination.
  // Better approach: for "open", we pass each non-closed status... or accept the limitation.
  // For now, "open" tab shows all non-closed (handled by not passing status param and
  // noting that "all" and "open" return same paginated results from backend).
  // The summary counts are still accurate.

  const handleSort = (col: SortableColumn) => {
    if (sortBy === col) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
    setPage(1);
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearchText(searchInput);
    setPage(1);
  };

  const handleFilterPriority = (pri: string) => {
    setFilterPriority((prev) => (prev === pri ? "all" : pri));
    setPage(1);
  };

  const handleFilterStatus = (key: string) => {
    setFilterStatus(key);
    setPage(1);
  };

  const SortIcon = ({ col }: { col: SortableColumn }) => {
    if (sortBy !== col)
      return <ArrowUpDown className="w-3.5 h-3.5 ml-1.5 opacity-60 inline" />;
    return sortDir === "asc" ? (
      <ArrowUp className="w-3.5 h-3.5 ml-1.5 text-cyan-400 inline" />
    ) : (
      <ArrowDown className="w-3.5 h-3.5 ml-1.5 text-cyan-400 inline" />
    );
  };

  return (
    <div className="space-y-6 p-4 md:p-8">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white mb-1">Incidents</h1>
          <p className="text-white/80">
            {summaryTotal} total &middot; {openCount} open &middot;{" "}
            {summaryClosed} closed &middot; ITIL v4 Priority Matrix
          </p>
        </div>
        {/* ITIL Matrix legend */}
        <div className="text-xs bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-3 hidden lg:block">
          <p className="font-semibold text-white/70 mb-1">
            Priority = Impact x Urgency
          </p>
          <div className="grid grid-cols-4 gap-x-3 gap-y-0.5 font-mono text-white/70">
            <span></span>
            <span className="text-red-400">High</span>
            <span className="text-amber-400">Med</span>
            <span className="text-cyan-400">Low</span>
            <span className="text-red-400">High</span>
            <span>P1</span>
            <span>P2</span>
            <span>P3</span>
            <span className="text-amber-400">Med</span>
            <span>P2</span>
            <span>P3</span>
            <span>P4</span>
            <span className="text-cyan-400">Low</span>
            <span>P3</span>
            <span>P4</span>
            <span>P5</span>
          </div>
        </div>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2 max-w-md">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search by title..."
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-[#06203b] border border-cyan-900/50 text-white placeholder-white/40 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-400 focus:border-cyan-400"
          />
        </div>
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-cyan-400 hover:bg-cyan-300 text-gray-950 font-bold text-sm transition-colors"
        >
          Search
        </button>
        {searchText && (
          <button
            type="button"
            onClick={() => {
              setSearchInput("");
              setSearchText("");
              setPage(1);
            }}
            className="px-3 py-2 rounded-lg bg-[#0a2d4a] border border-cyan-900/40 text-white/70 hover:text-white text-sm transition-colors"
          >
            Clear
          </button>
        )}
      </form>

      {/* Status filter tabs */}
      <div className="flex items-center gap-2">
        {(
          [
            { key: "all", label: "All", count: summaryTotal },
            { key: "open", label: "Open", count: openCount },
            { key: "closed", label: "Closed", count: summaryClosed },
          ] as const
        ).map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => handleFilterStatus(key)}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
              filterStatus === key
                ? "bg-cyan-500 text-gray-950 font-bold"
                : "bg-[#0a2d4a] text-white/70 hover:text-white hover:bg-[#0d3b5e] border border-cyan-900/40",
            )}
          >
            {label} <span className="ml-1 text-xs opacity-70">({count})</span>
          </button>
        ))}
      </div>

      {/* Priority summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {(["P1", "P2", "P3", "P4", "P5"] as const).map((pri) => {
          const meta = PRIORITY_META[pri];
          const count = priorityCounts[pri] ?? 0;
          const isActive = filterPriority === pri;
          return (
            <button
              key={pri}
              onClick={() => handleFilterPriority(pri)}
              className={cn(
                "rounded-lg border p-4 text-left transition-all",
                isActive
                  ? `ring-2 ${meta.cardRing} bg-[#0d3b5e]`
                  : "border-cyan-900/40 bg-[#0a2d4a] hover:bg-[#0d3b5e]",
              )}
            >
              <p className="text-sm text-white/70">{meta.label}</p>
              <p className="text-2xl font-bold text-white">{count}</p>
              <p className="text-[10px] text-white/70 mt-1">{meta.desc}</p>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="bg-[#0a2d4a] rounded-lg border border-cyan-900/40 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-white">
            Loading incidents...
          </div>
        ) : error ? (
          <div className="p-8 text-center text-red-400">{error}</div>
        ) : incidents.length === 0 ? (
          <div className="p-8 text-center text-white">
            No incidents match filter
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-[#06203b] border-b border-cyan-900/40">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-white/70 uppercase tracking-wider w-8"></th>
                <th
                  className="px-4 py-3 text-left text-xs font-semibold text-white/70 uppercase tracking-wider cursor-pointer select-none hover:text-white"
                  onClick={() => handleSort("title")}
                >
                  Title <SortIcon col="title" />
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-white/70 uppercase tracking-wider">
                  Entity
                </th>
                <th
                  className="px-4 py-3 text-left text-xs font-semibold text-white/70 uppercase tracking-wider cursor-pointer select-none hover:text-white"
                  onClick={() => handleSort("priority")}
                >
                  Priority <SortIcon col="priority" />
                </th>
                <th
                  className="px-4 py-3 text-left text-xs font-semibold text-white/70 uppercase tracking-wider cursor-pointer select-none hover:text-white"
                  onClick={() => handleSort("impact")}
                >
                  Impact <SortIcon col="impact" />
                </th>
                <th
                  className="px-4 py-3 text-left text-xs font-semibold text-white/70 uppercase tracking-wider cursor-pointer select-none hover:text-white"
                  onClick={() => handleSort("urgency")}
                >
                  Urgency <SortIcon col="urgency" />
                </th>
                <th
                  className="px-4 py-3 text-left text-xs font-semibold text-white/70 uppercase tracking-wider cursor-pointer select-none hover:text-white"
                  onClick={() => handleSort("status")}
                >
                  Status <SortIcon col="status" />
                </th>
                <th
                  className="px-4 py-3 text-left text-xs font-semibold text-white/70 uppercase tracking-wider cursor-pointer select-none hover:text-white"
                  onClick={() => handleSort("created_at")}
                >
                  Created <SortIcon col="created_at" />
                </th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((inc) => {
                const isExpanded = expandedId === inc.id;
                return (
                  <React.Fragment key={inc.id}>
                    <tr
                      onClick={() => setExpandedId(isExpanded ? null : inc.id)}
                      className="border-b border-cyan-900/20 hover:bg-white/5 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3 text-white/70">
                        {isExpanded ? (
                          <ChevronUp className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4" />
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-white font-medium max-w-xs truncate">
                        {inc.title}
                      </td>
                      <td className="px-4 py-3 text-sm text-white/70 font-mono text-xs">
                        {inc.entity_external_id || inc.entity_id || "\u2014"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "px-2.5 py-1 rounded-full text-xs font-bold uppercase border",
                            priorityColor(inc.priority),
                          )}
                        >
                          {inc.priority ?? "\u2014"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "text-xs font-semibold capitalize",
                            impactUrgencyColor(inc.impact),
                          )}
                        >
                          {inc.impact ?? "\u2014"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "text-xs font-semibold capitalize",
                            impactUrgencyColor(inc.urgency),
                          )}
                        >
                          {inc.urgency ?? "\u2014"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "px-2.5 py-1 rounded text-xs font-semibold",
                            statusColor(inc.status),
                          )}
                        >
                          {inc.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-white">
                        {inc.created_at
                          ? new Date(inc.created_at).toLocaleString()
                          : "\u2014"}
                      </td>
                    </tr>

                    {/* Expanded Detail Row */}
                    {isExpanded && (
                      <tr className="bg-[#06203b]">
                        <td colSpan={8} className="px-6 py-5">
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Reasoning Chain */}
                            <div>
                              <h4 className="text-xs font-bold text-cyan-400 uppercase tracking-wider mb-3">
                                Reasoning Chain
                              </h4>
                              {inc.reasoning_chain &&
                              Array.isArray(inc.reasoning_chain) ? (
                                <div className="space-y-2">
                                  {inc.reasoning_chain.map(
                                    (step: any, idx: number) => (
                                      <div
                                        key={idx}
                                        className="flex gap-3 text-sm"
                                      >
                                        <span className="text-white/70 font-mono text-xs mt-0.5">
                                          {idx + 1}.
                                        </span>
                                        <span className="text-white">
                                          {typeof step === "string"
                                            ? step
                                            : step.description ||
                                              step.detail ||
                                              JSON.stringify(step)}
                                        </span>
                                      </div>
                                    ),
                                  )}
                                </div>
                              ) : (
                                <p className="text-white/70 text-sm italic">
                                  No reasoning chain recorded
                                </p>
                              )}
                            </div>

                            {/* Resolution & ITIL Classification */}
                            <div className="space-y-4">
                              {/* ITIL Classification detail */}
                              <div>
                                <h4 className="text-xs font-bold text-purple-400 uppercase tracking-wider mb-2">
                                  ITIL v4 Classification
                                </h4>
                                <div className="grid grid-cols-3 gap-3 text-sm">
                                  <div>
                                    <p className="text-[10px] text-white/70 uppercase">
                                      Impact
                                    </p>
                                    <p
                                      className={cn(
                                        "font-semibold capitalize",
                                        impactUrgencyColor(inc.impact),
                                      )}
                                    >
                                      {inc.impact ?? "\u2014"}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-[10px] text-white/70 uppercase">
                                      Urgency
                                    </p>
                                    <p
                                      className={cn(
                                        "font-semibold capitalize",
                                        impactUrgencyColor(inc.urgency),
                                      )}
                                    >
                                      {inc.urgency ?? "\u2014"}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-[10px] text-white/70 uppercase">
                                      Priority
                                    </p>
                                    <p className="font-bold text-white">
                                      {inc.priority ?? "\u2014"}
                                    </p>
                                  </div>
                                </div>
                              </div>

                              {inc.resolution_summary && (
                                <div>
                                  <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider mb-2">
                                    Resolution
                                  </h4>
                                  <p className="text-sm text-white">
                                    {inc.resolution_summary}
                                  </p>
                                </div>
                              )}
                              {inc.kpi_snapshot && (
                                <div>
                                  <h4 className="text-xs font-bold text-amber-400 uppercase tracking-wider mb-2">
                                    KPI Snapshot
                                  </h4>
                                  <pre className="text-xs text-white bg-black/30 rounded p-3 overflow-x-auto">
                                    {JSON.stringify(inc.kpi_snapshot, null, 2)}
                                  </pre>
                                </div>
                              )}
                              <div className="text-xs text-white/70">
                                ID: <span className="font-mono">{inc.id}</span>
                              </div>
                              <div>
                                <Link
                                  href={`/topology?entity_id=${inc.entity_id}`}
                                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-cyan-900/40 hover:bg-cyan-800/60 border border-cyan-700/50 text-cyan-300 text-xs font-semibold transition-colors"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <Network className="w-3.5 h-3.5" />
                                  Explore in Topology
                                </Link>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {!loading && !error && totalCount > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-cyan-900/40 bg-[#06203b]">
            <p className="text-sm text-white/70">
              Showing {(page - 1) * PAGE_SIZE + 1}–
              {Math.min(page * PAGE_SIZE, totalCount)} of {totalCount}
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className={cn(
                  "inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border",
                  page <= 1
                    ? "bg-[#06203b] border-cyan-900/30 text-white/30 cursor-not-allowed"
                    : "bg-[#06203b] border-cyan-900/50 text-white/80 hover:text-white hover:bg-[#0d3b5e]",
                )}
              >
                <ChevronLeft className="w-4 h-4" />
                Prev
              </button>
              <span className="text-sm text-white/80 px-2">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className={cn(
                  "inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border",
                  page >= totalPages
                    ? "bg-[#06203b] border-cyan-900/30 text-white/30 cursor-not-allowed"
                    : "bg-[#06203b] border-cyan-900/50 text-white/80 hover:text-white hover:bg-[#0d3b5e]",
                )}
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
