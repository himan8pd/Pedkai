"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

interface SleepingCell {
  cellId: string;
  site: string;
  domain: string;
  kpiDeviation: number;
  decayScore: number;
  lastSeen: string;
  status: "SLEEPING" | "RECOVERING" | "HEALTHY";
}

const EXAMPLE_CELLS: SleepingCell[] = [
  {
    cellId: "JKTBND001-SEC1",
    site: "Jakarta Bundaran HI",
    domain: "RAN",
    kpiDeviation: -34.2,
    decayScore: 0.81,
    lastSeen: "2026-03-11 02:14:07",
    status: "SLEEPING",
  },
  {
    cellId: "SBYBDR002-SEC3",
    site: "Surabaya Bundaran Raya",
    domain: "RAN",
    kpiDeviation: -18.7,
    decayScore: 0.47,
    lastSeen: "2026-03-11 03:52:31",
    status: "RECOVERING",
  },
  {
    cellId: "BDGDGO003-SEC2",
    site: "Bandung Dago Utama",
    domain: "Core",
    kpiDeviation: -5.1,
    decayScore: 0.12,
    lastSeen: "2026-03-11 04:01:55",
    status: "HEALTHY",
  },
];

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

export default function SleepingCellsPage() {
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState<string | null>(null);

  function handleRunDetection() {
    setRunning(true);
    setTimeout(() => {
      setRunning(false);
      setLastRun(new Date().toLocaleString());
    }, 2000);
  }

  const monitored = EXAMPLE_CELLS.length;
  const activeSleeping = EXAMPLE_CELLS.filter((c) => c.status === "SLEEPING").length;
  const avgDecay =
    EXAMPLE_CELLS.reduce((sum, c) => sum + c.decayScore, 0) / EXAMPLE_CELLS.length;

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
        <p className="text-white/60 text-xs">Last detection run: {lastRun}</p>
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
          (0–1) measures accumulated deviation from baseline; scores above{" "}
          <span className="text-amber-300 font-semibold">0.6</span> are flagged
          as actively sleeping.
        </p>
      </div>

      {/* KPI stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-5">
          <p className="text-xs font-semibold text-white/60 uppercase tracking-wider mb-1">
            Cells Monitored
          </p>
          <p className="text-4xl font-bold text-white">{monitored}</p>
        </div>
        <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-5">
          <p className="text-xs font-semibold text-white/60 uppercase tracking-wider mb-1">
            Active Sleeping Cells
          </p>
          <p className="text-4xl font-bold text-amber-300">{activeSleeping}</p>
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

      {/* Table */}
      <div className="bg-[#0a2d4a] rounded-lg border border-cyan-900/40 overflow-hidden">
        <table className="w-full">
          <thead className="bg-[#06203b] border-b border-cyan-900/40">
            <tr>
              {[
                "Cell ID",
                "Site",
                "Domain",
                "KPI Deviation (%)",
                "Decay Score",
                "Last Seen",
                "Status",
              ].map((col) => (
                <th
                  key={col}
                  className="px-4 py-3 text-left text-xs font-semibold text-white/60 uppercase tracking-wider"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {EXAMPLE_CELLS.map((cell) => (
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
                  {cell.lastSeen}
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
      </div>
    </div>
  );
}
