"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  Clock,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Network,
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
    color: "bg-gray-800/60 text-gray-300 border-gray-600",
    cardRing: "ring-gray-500 border-gray-500",
  },
};

function priorityColor(p: string | null) {
  return (
    PRIORITY_META[p ?? ""]?.color ?? "bg-gray-800 text-gray-300 border-gray-700"
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
      return "bg-gray-800 text-gray-300";
  }
}

export default function IncidentsPage() {
  const { token, tenantId } = useAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterPriority, setFilterPriority] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");

  useEffect(() => {
    async function fetchIncidents() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/incidents/`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setIncidents(data);
      } catch (err: any) {
        setError(err.message ?? "Failed to load incidents");
      } finally {
        setLoading(false);
      }
    }
    if (token && tenantId) fetchIncidents();
  }, [token, tenantId]);

  const afterStatusFilter =
    filterStatus === "all"
      ? incidents
      : filterStatus === "open"
        ? incidents.filter((i) => i.status !== "closed")
        : incidents.filter((i) => i.status === "closed");

  const filtered =
    filterPriority === "all"
      ? afterStatusFilter
      : afterStatusFilter.filter((i) => i.priority === filterPriority);

  const openCount = incidents.filter((i) => i.status !== "closed").length;
  const closedCount = incidents.filter((i) => i.status === "closed").length;

  const priorityCounts = incidents.reduce(
    (acc, i) => {
      const p = i.priority ?? "Unknown";
      acc[p] = (acc[p] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  return (
    <div className="space-y-6 p-4 md:p-8">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white mb-1">Incidents</h1>
          <p className="text-white/80">
            {incidents.length} total &middot; {openCount} open &middot;{" "}
            {closedCount} closed &middot; ITIL v4 Priority Matrix
          </p>
        </div>
        {/* ITIL Matrix legend */}
        <div className="text-xs bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-3 hidden lg:block">
          <p className="font-semibold text-slate-300 mb-1">
            Priority = Impact × Urgency
          </p>
          <div className="grid grid-cols-4 gap-x-3 gap-y-0.5 font-mono text-slate-300">
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

      {/* Status filter tabs */}
      <div className="flex items-center gap-2">
        {(
          [
            { key: "all", label: "All", count: incidents.length },
            { key: "open", label: "Open", count: openCount },
            { key: "closed", label: "Closed", count: closedCount },
          ] as const
        ).map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => setFilterStatus(key)}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
              filterStatus === key
                ? "bg-cyan-500 text-gray-950 font-bold"
                : "bg-[#0a2d4a] text-slate-300 hover:text-white hover:bg-[#0d3b5e] border border-cyan-900/40",
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
              onClick={() => setFilterPriority(isActive ? "all" : pri)}
              className={cn(
                "rounded-lg border p-4 text-left transition-all",
                isActive
                  ? `ring-2 ${meta.cardRing} bg-[#0d3b5e]`
                  : "border-cyan-900/40 bg-[#0a2d4a] hover:bg-[#0d3b5e]",
              )}
            >
              <p className="text-sm text-slate-300">{meta.label}</p>
              <p className="text-2xl font-bold text-white">{count}</p>
              <p className="text-[10px] text-slate-400 mt-1">{meta.desc}</p>
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
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-white">
            No incidents match filter
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-[#06203b] border-b border-cyan-900/40">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider w-8"></th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Title
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Entity
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Priority
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Impact
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Urgency
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Created
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((inc) => {
                const isExpanded = expandedId === inc.id;
                return (
                  <React.Fragment key={inc.id}>
                    <tr
                      onClick={() => setExpandedId(isExpanded ? null : inc.id)}
                      className="border-b border-cyan-900/20 hover:bg-white/5 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3 text-slate-400">
                        {isExpanded ? (
                          <ChevronUp className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4" />
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-white font-medium max-w-xs truncate">
                        {inc.title}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-300 font-mono text-xs">
                        {inc.entity_external_id || inc.entity_id || "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "px-2.5 py-1 rounded-full text-xs font-bold uppercase border",
                            priorityColor(inc.priority),
                          )}
                        >
                          {inc.priority ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "text-xs font-semibold capitalize",
                            impactUrgencyColor(inc.impact),
                          )}
                        >
                          {inc.impact ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "text-xs font-semibold capitalize",
                            impactUrgencyColor(inc.urgency),
                          )}
                        >
                          {inc.urgency ?? "—"}
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
                          : "—"}
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
                                        <span className="text-slate-400 font-mono text-xs mt-0.5">
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
                                <p className="text-slate-400 text-sm italic">
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
                                    <p className="text-[10px] text-slate-400 uppercase">
                                      Impact
                                    </p>
                                    <p
                                      className={cn(
                                        "font-semibold capitalize",
                                        impactUrgencyColor(inc.impact),
                                      )}
                                    >
                                      {inc.impact ?? "—"}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-[10px] text-slate-400 uppercase">
                                      Urgency
                                    </p>
                                    <p
                                      className={cn(
                                        "font-semibold capitalize",
                                        impactUrgencyColor(inc.urgency),
                                      )}
                                    >
                                      {inc.urgency ?? "—"}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-[10px] text-slate-400 uppercase">
                                      Priority
                                    </p>
                                    <p className="font-bold text-white">
                                      {inc.priority ?? "—"}
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
                              <div className="text-xs text-slate-400">
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
      </div>
    </div>
  );
}
