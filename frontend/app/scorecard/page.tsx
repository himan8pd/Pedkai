"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Shield,
  Activity,
  Clock,
  ChevronDown,
  ChevronUp,
  BarChart3,
  Target,
  Zap,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import * as Cache from "@/app/apiCache";
import { useAuth } from "@/app/context/AuthContext";

interface ScorecardData {
  pedkai_zone_mttr_minutes: number | null;
  pedkai_zone_incident_count: number;
  pedkai_zone_closed_count: number;
  non_pedkai_zone_mttr_minutes: number | null;
  non_pedkai_zone_incident_count: number | null;
  improvement_pct: number | null;
  period_start: string;
  period_end: string;
  value_protected: {
    revenue_protected: number | null;
    incidents_prevented: number | null;
    uptime_gained_minutes: number | null;
    methodology_doc_url: string;
    confidence_interval: string | null;
  };
  baseline_status: string | null;
  baseline_note: string | null;
  drift_calibration: any;
}

interface Detection {
  entity_id: string;
  entity_name: string;
  metric_name: string;
  current_value: number;
  baseline_value: number;
  drift_pct: number;
  severity: string;
  recommendation: string;
  ai_generated: boolean;
  ai_watermark: string;
}

interface ValueCapture {
  revenue_protected: number;
  incidents_prevented: number;
  uptime_gained_minutes: number;
}

function KpiCard({
  label,
  value,
  subtitle,
  icon,
  trend,
  color = "blue",
  calculation,
}: {
  label: string;
  value: string;
  subtitle?: string;
  icon: React.ReactNode;
  trend?: "up" | "down" | null;
  color?: string;
  calculation?: string;
}) {
  const [showCalc, setShowCalc] = React.useState(false);
  const colorMap: Record<string, string> = {
    blue: "from-cyan-500/20 to-cyan-600/5 border-cyan-500/30",
    green: "from-emerald-500/20 to-emerald-600/5 border-emerald-500/30",
    amber: "from-amber-500/20 to-amber-600/5 border-amber-500/30",
    red: "from-red-500/20 to-red-600/5 border-red-500/30",
    purple: "from-purple-500/20 to-purple-600/5 border-purple-500/30",
    cyan: "from-cyan-500/20 to-cyan-600/5 border-cyan-500/30",
  };
  return (
    <div
      className={cn(
        "rounded-xl border p-5 bg-gradient-to-br transition-all hover:scale-[1.02] relative",
        colorMap[color] || colorMap.blue,
      )}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white/55 uppercase tracking-wider">
          {label}
        </h3>
        <div className="flex items-center gap-1.5">
          {calculation && (
            <button
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowCalc(!showCalc); }}
              className="text-white/30 hover:text-white/70 transition-colors"
              title="How this is calculated"
            >
              <Info className="w-3.5 h-3.5" />
            </button>
          )}
          <div className="text-white/55">{icon}</div>
        </div>
      </div>
      <p className="text-3xl font-bold text-white">{value}</p>
      {subtitle && (
        <div className="flex items-center gap-1 mt-2">
          {trend === "up" && (
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
          )}
          {trend === "down" && (
            <TrendingDown className="w-3.5 h-3.5 text-red-400" />
          )}
          <p className="text-sm text-white/55">{subtitle}</p>
        </div>
      )}
      {showCalc && calculation && (
        <div className="mt-3 pt-3 border-t border-white/10 text-xs text-white/60 leading-relaxed">
          {calculation}
        </div>
      )}
    </div>
  );
}

export default function ScorecardPage() {
  const { token, tenantId, authFetch } = useAuth();
  const [scorecard, setScorecard] = useState<ScorecardData | null>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [valueCapture, setValueCapture] = useState<ValueCapture | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showDetections, setShowDetections] = useState(true);
  const [showMethodology, setShowMethodology] = useState(true);

  useEffect(() => {
    async function fetchAll() {
      if (!token || !tenantId) {
        setLoading(false); // don't hang forever if auth isn't ready
        return;
      }

      // Restore from cache instantly (stale-while-revalidate)
      const scKey = `scorecard:${tenantId}`;
      const detKey = `scorecard-detections:${tenantId}`;
      const valKey = `scorecard-value:${tenantId}`;

      const cachedSc = Cache.get<ScorecardData>(scKey, Cache.TTL.MEDIUM);
      const cachedDet = Cache.get<Detection[]>(detKey, Cache.TTL.MEDIUM);
      const cachedVal = Cache.get<ValueCapture>(valKey, Cache.TTL.MEDIUM);

      if (cachedSc) setScorecard(cachedSc);
      if (cachedDet) setDetections(cachedDet);
      if (cachedVal) setValueCapture(cachedVal);
      if (cachedSc && cachedDet && cachedVal) setLoading(false);

      try {
        const [scRes, detRes, valRes] = await Promise.allSettled([
          authFetch("/api/v1/autonomous/scorecard"),
          authFetch("/api/v1/autonomous/detections"),
          authFetch("/api/v1/autonomous/value-capture"),
        ]);

        if (scRes.status === "fulfilled" && scRes.value.ok) {
          const d = await scRes.value.json();
          setScorecard(d);
          Cache.set(scKey, d);
        }
        if (detRes.status === "fulfilled" && detRes.value.ok) {
          const d = await detRes.value.json();
          setDetections(d);
          Cache.set(detKey, d);
        }
        if (valRes.status === "fulfilled" && valRes.value.ok) {
          const d = await valRes.value.json();
          setValueCapture(d);
          Cache.set(valKey, d);
        }
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    fetchAll();
  }, [token, tenantId]);

  if (loading)
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-white/55 animate-pulse text-lg">
          Loading scorecard...
        </div>
      </div>
    );

  return (
    <div className="space-y-8 p-4 md:p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-1">AI Scorecard</h1>
        <p className="text-white/80">
          Autonomous intelligence performance &middot;{" "}
          {scorecard ? (
            <>
              {new Date(scorecard.period_start).toLocaleDateString()} &ndash;{" "}
              {new Date(scorecard.period_end).toLocaleDateString()}
            </>
          ) : (
            "Last 30 days"
          )}
        </p>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-red-900/30 border border-red-700 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Primary KPI Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        <Link href="/incidents" className="block">
          <KpiCard
            label="Mean Time to Resolve"
            value={
              scorecard?.pedkai_zone_mttr_minutes != null
                ? `${scorecard.pedkai_zone_mttr_minutes} min`
                : "Pending"
            }
            subtitle={
              scorecard?.pedkai_zone_mttr_minutes != null
                ? "Pedkai-managed zone"
                : scorecard?.pedkai_zone_closed_count
                  ? `${scorecard.pedkai_zone_closed_count.toLocaleString()} closed — computing`
                  : "No closed incidents yet"
            }
            icon={<Clock className="w-5 h-5" />}
            trend={scorecard?.pedkai_zone_mttr_minutes != null ? "down" : null}
            color="cyan"
            calculation="Average (closed_at - created_at) in minutes across all closed incidents in the Pedkai-managed zone during the reporting period."
          />
        </Link>
        <Link href="/incidents" className="block">
          <KpiCard
            label="Incidents Tracked"
            value={String(scorecard?.pedkai_zone_incident_count ?? 0)}
            subtitle={
              scorecard?.pedkai_zone_closed_count
                ? `${scorecard.pedkai_zone_closed_count.toLocaleString()} closed · ${((scorecard.pedkai_zone_incident_count ?? 0) - (scorecard.pedkai_zone_closed_count ?? 0)).toLocaleString()} open`
                : "Active monitoring window"
            }
            icon={<AlertCircle className="w-5 h-5" />}
            color="amber"
            calculation="Total incidents created from correlated alarms within the monitoring window for this tenant."
          />
        </Link>
        <Link href="#detections" className="block">
          <KpiCard
            label="Drift Detections"
            value={String(detections.length)}
            subtitle="KPI anomalies flagged"
            icon={<Activity className="w-5 h-5" />}
            color="purple"
            calculation="Count of KPI metrics that deviated beyond the configured z-score threshold compared to their 7-day rolling baseline."
          />
        </Link>
        <Link href="/incidents" className="block">
          <KpiCard
            label="Revenue Protected"
            value={
              valueCapture?.revenue_protected != null
                ? `$${(valueCapture.revenue_protected / 1000).toFixed(0)}K`
                : "N/A"
            }
            subtitle={
              valueCapture
                ? "Based on closed incidents"
                : "Awaiting incident closure"
            }
            icon={<Target className="w-5 h-5" />}
            trend={valueCapture?.revenue_protected ? "up" : null}
            color="green"
            calculation="Sum of (MTTR_reduction x revenue_per_minute) for each closed incident, where MTTR reduction is estimated against the non-Pedkai baseline zone."
          />
        </Link>
        <Link href="/incidents" className="block">
          <KpiCard
            label="Incidents Prevented"
            value={String(valueCapture?.incidents_prevented ?? "—")}
            subtitle="Proactive shield interventions"
            icon={<Shield className="w-5 h-5" />}
            color="blue"
            calculation="Count of autonomous shield actions that resolved drift detections before they escalated to customer-impacting incidents."
          />
        </Link>
        <Link href="/incidents" className="block">
          <KpiCard
            label="Uptime Recovered"
            value={
              valueCapture?.uptime_gained_minutes != null
                ? `${valueCapture.uptime_gained_minutes.toFixed(0)} min`
                : "—"
            }
            subtitle="From automated resolution"
            icon={<Zap className="w-5 h-5" />}
            color="green"
            calculation="Sum of time saved per incident: (baseline_MTTR - actual_MTTR) across all incidents resolved with autonomous assistance."
          />
        </Link>
      </div>

      {/* Baseline Status */}
      {scorecard && (!scorecard.baseline_status || scorecard.baseline_status === "pending_shadow_mode_collection") && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-5">
          <div className="flex items-start gap-3">
            <BarChart3 className="w-5 h-5 text-amber-400 mt-0.5 shrink-0" />
            <div>
              <h3 className="text-amber-300 font-semibold text-sm">
                Counterfactual Baseline Pending
              </h3>
              <p className="text-white/80 text-sm mt-1">
                {scorecard.baseline_note ?? "Counterfactual baseline data has not yet been collected. MTTR comparisons against a non-Pedkai zone require a parallel observation period."}
              </p>
              <p className="text-white/60 text-xs mt-2">
                Non-Pedkai zone comparison will be available after 30-day
                shadow-mode deployment.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Drift Calibration */}
      {scorecard?.drift_calibration && !scorecard.drift_calibration.error && (
        <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5">
          <h3 className="text-white font-semibold mb-3 flex items-center gap-2">
            <Activity className="w-4 h-4 text-purple-400" />
            Drift Calibration
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Object.entries(scorecard.drift_calibration).map(([key, val]) => (
              <div key={key}>
                <p className="text-xs text-white/55 uppercase tracking-wider">
                  {key.replace(/_/g, " ")}
                </p>
                <p className="text-white font-mono text-sm mt-1">
                  {typeof val === "number" ? val.toFixed(3) : String(val)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* KPI Drift Detections */}
      <div id="detections" className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] overflow-hidden">
        <button
          onClick={() => setShowDetections(!showDetections)}
          className="w-full px-5 py-4 flex items-center justify-between hover:bg-[#0d3b5e] transition-colors"
        >
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Shield className="w-5 h-5 text-cyan-400" />
            Autonomous Shield Detections
            <span className="text-sm font-normal text-white/70">
              ({detections.length})
            </span>
          </h2>
          {showDetections ? (
            <ChevronUp className="w-5 h-5 text-white/55" />
          ) : (
            <ChevronDown className="w-5 h-5 text-white/55" />
          )}
        </button>

        {showDetections && (
          <div className="border-t border-cyan-900/40">
            {detections.length === 0 ? (
              <div className="p-6 text-center text-white">
                No drift detections in current window
              </div>
            ) : (
              <div className="divide-y divide-cyan-900/30">
                {detections.map((det, idx) => (
                  <div key={idx} className="px-5 py-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-white font-medium">
                          {det.entity_name}
                        </p>
                        <p className="text-sm text-white/80 mt-0.5">
                          {det.metric_name}:{" "}
                          <span className="text-white font-mono">
                            {det.current_value.toFixed(2)}
                          </span>{" "}
                          (baseline: {det.baseline_value.toFixed(2)})
                        </p>
                      </div>
                      <span
                        className={cn(
                          "px-2 py-1 rounded text-xs font-bold uppercase",
                          det.severity === "high"
                            ? "bg-red-900/50 text-red-300"
                            : det.severity === "medium"
                              ? "bg-amber-900/50 text-amber-300"
                              : "bg-slate-700/50 text-slate-200",
                        )}
                      >
                        {det.severity}
                      </span>
                    </div>
                    {det.recommendation && (
                      <p className="text-sm text-cyan-400 mt-2 italic">
                        &quot;{det.recommendation}&quot;
                      </p>
                    )}
                    {det.ai_generated && (
                      <span className="inline-flex items-center gap-1 mt-2 text-[10px] text-amber-400/80 uppercase tracking-wider">
                        AI Generated — Advisory Only
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Methodology Footer */}
      <div className="rounded-xl border border-cyan-900/40 bg-[#0a2d4a] p-5">
        <button
          onClick={() => setShowMethodology(!showMethodology)}
          className="flex items-center gap-2 text-sm text-white hover:text-cyan-300 transition-colors"
        >
          {showMethodology ? (
            <ChevronUp className="w-4 h-4" />
          ) : (
            <ChevronDown className="w-4 h-4" />
          )}
          Methodology & Data Sources
        </button>
        {showMethodology && (
          <div className="mt-3 text-sm text-white/80 space-y-2">
            <p>
              MTTR is calculated from actual incident created_at → closed_at
              timestamps in PostgreSQL.
            </p>
            <p>
              Revenue protection uses policy-engine derived risk parameters per
              incident severity tier.
            </p>
            <p>
              Drift detections use Z-score analysis against rolling KPI
              baselines from TimescaleDB.
            </p>
            <p>
              Non-Pedkai zone comparison requires 30-day shadow-mode data (not
              yet collected).
            </p>
            <p className="text-white/60">
              Full methodology:{" "}
              <span className="font-mono text-xs">
                /docs/value_methodology.md
              </span>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
