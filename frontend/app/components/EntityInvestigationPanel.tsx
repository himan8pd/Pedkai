"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  X, Loader2, Sparkles, Clock, Layers, Boxes, Activity, GitBranch,
  AlertTriangle, ChevronRight,
} from "lucide-react";
import { useAuth } from "@/app/context/AuthContext";

/* ── Response types (mirror backend EntityInvestigationResponse) ── */
interface EvidenceItem {
  fragment_id: string;
  source_type: string;
  event_timestamp: string | null;
  snap_status: string;
  current_decay_score: number;
  snippet: string;
  primary_failure_mode: string | null;
  embedded: boolean;
}
interface SnapCard {
  fragment_id: string;
  matched_fragment_id: string;
  matched_snippet: string;
  matched_source_type: string | null;
  failure_mode: string | null;
  relation_label: string;
  final_score: number;
  decision: string | null;
  evaluated_at: string | null;
  dimensions: Record<string, number | null>;
  dominant_driver: string | null;
  why: string;
  rescored_live: boolean;
}
interface DivergenceFlag {
  divergence_type: string;
  confidence: number;
  description: string | null;
  attribute_name: string | null;
  cmdb_value: string | null;
  observed_value: string | null;
}
interface Investigation {
  entity_identifier: string;
  tenant_id: string;
  embedding_status: string;
  fragment_count: number;
  embedded_count: number;
  evidence: EvidenceItem[];
  snaps: SnapCard[];
  divergence: DivergenceFlag[];
}

/* ── Presentation helpers ── */
const DIVERGENCE_STYLE: Record<string, string> = {
  dark_node: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  phantom_node: "bg-violet-500/15 text-violet-300 border-violet-500/40",
  dark_edge: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40",
  phantom_edge: "bg-slate-500/15 text-slate-300 border-slate-500/40",
  dark_attribute: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  identity_mutation: "bg-orange-500/15 text-orange-300 border-orange-500/40",
};

/* Ordered dimensions for the "why" bars. */
const DIMENSIONS: { key: string; label: string; icon: React.ReactNode }[] = [
  { key: "semantic", label: "Semantic (T-VEC)", icon: <Sparkles className="w-3 h-3" /> },
  { key: "topological", label: "Topology", icon: <Layers className="w-3 h-3" /> },
  { key: "temporal", label: "Time", icon: <Clock className="w-3 h-3" /> },
  { key: "entity_overlap", label: "Entity overlap", icon: <Boxes className="w-3 h-3" /> },
  { key: "operational", label: "Operational", icon: <Activity className="w-3 h-3" /> },
];

/* UX-02: summarise how much evidence backed a snap from the existing nulls.
   null in a dimension already means "unavailable"; a snap scored on 2 of 5
   dimensions must look different from one scored on all 5. */
function sufficiency(dims: Record<string, number | null>): { label: string; cls: string } {
  const n = DIMENSIONS.filter((d) => dims[d.key] != null).length;
  if (n >= 4) return { label: "FULL EVIDENCE", cls: "text-emerald-300 bg-emerald-500/15 border-emerald-500/40" };
  if (n >= 2) return { label: "PARTIAL EVIDENCE", cls: "text-amber-300 bg-amber-500/15 border-amber-500/40" };
  return { label: "MINIMAL EVIDENCE", cls: "text-red-300 bg-red-500/15 border-red-500/40" };
}

const SNAP_STATUS_DOT: Record<string, string> = {
  SNAPPED: "bg-cyan-400", ACTIVE: "bg-emerald-400", NEAR_MISS: "bg-amber-400",
  STALE: "bg-slate-500", EXPIRED: "bg-red-500", COLD: "bg-slate-600", INGESTED: "bg-violet-400",
};

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { year: "2-digit", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/* One dimension bar. Null = dimension unavailable for the pair. */
function DimBar({ label, icon, value, dominant }: { label: string; icon: React.ReactNode; value: number | null; dominant: boolean }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2">
      <div className={`flex items-center gap-1 w-32 shrink-0 text-[11px] ${dominant ? "text-cyan-300 font-semibold" : "text-white/60"}`}>
        {icon}<span className="truncate">{label}</span>
      </div>
      <div className="flex-1 h-2 rounded-full bg-[#06203b] overflow-hidden">
        {value == null ? null : (
          <div
            className={`h-full rounded-full ${dominant ? "bg-cyan-400" : "bg-slate-500"}`}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      <div className={`w-10 text-right text-[11px] tabular-nums ${value == null ? "text-white/30" : dominant ? "text-cyan-300 font-semibold" : "text-white/70"}`}>
        {value == null ? "n/a" : value.toFixed(2)}
      </div>
    </div>
  );
}

export default function EntityInvestigationPanel({
  entityId,
  entityName,
  onClose,
}: {
  entityId: string;
  entityName?: string;
  onClose: () => void;
}) {
  const { authFetch } = useAuth();
  const [data, setData] = useState<Investigation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) { setLoading(true); setError(null); }
    try {
      const res = await authFetch(
        `/api/v1/abeyance/entity/${encodeURIComponent(entityId)}/investigation`,
      );
      if (res.status === 404) {
        setData(null);
        setError("No abeyance evidence or divergence records for this entity yet.");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: Investigation = await res.json();
      setData(json);
      setError(null);
      // Keep polling while embeddings compute in the background.
      if (json.embedding_status === "computing") {
        pollRef.current = setTimeout(() => load(true), 5000);
      }
    } catch (e: any) {
      setError(e.message ?? "Failed to load investigation");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [authFetch, entityId]);

  useEffect(() => {
    load();
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
  }, [load]);

  const computing = data?.embedding_status === "computing";

  return (
    <div className="flex flex-col h-full bg-[#0a2d4a] border-l border-cyan-900/40 w-[420px] max-w-[90vw]">
      {/* Header */}
      <div className="px-4 py-3 border-b border-cyan-900/40 bg-[#06203b] flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-cyan-400 text-[11px] font-semibold uppercase tracking-wider">
            <GitBranch className="w-3.5 h-3.5" /> Investigation
          </div>
          <div className="text-white font-bold text-sm mt-0.5 break-all leading-tight">
            {entityName || entityId}
          </div>
        </div>
        <button onClick={onClose} className="text-white/50 hover:text-white shrink-0 p-1">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center gap-2 text-cyan-400 text-sm py-10">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading investigation…
          </div>
        ) : error && !data ? (
          <div className="p-4 text-white/60 text-sm flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" /> {error}
          </div>
        ) : data ? (
          <div className="p-4 space-y-6">
            {/* ── SECTION: Inventory divergence (CMDB reconciliation) ── */}
            <section className="space-y-2">
              <div className="flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-300" />
                <h4 className="text-[11px] uppercase tracking-wider text-white/70 font-bold">Inventory divergence</h4>
              </div>
              <p className="text-[10px] text-white/40">What the CMDB gets wrong — reconciliation vs. reality</p>
              {data.divergence.length > 0 ? (
                <>
                  <div className="flex flex-wrap gap-1.5">
                    {data.divergence.map((d, i) => (
                      <span
                        key={i}
                        title={d.description ?? ""}
                        className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border ${DIVERGENCE_STYLE[d.divergence_type] ?? "bg-slate-500/15 text-slate-300 border-slate-500/40"}`}
                      >
                        {d.divergence_type.replace(/_/g, " ")}
                        <span className="opacity-70">{Math.round((d.confidence ?? 0) * 100)}%</span>
                      </span>
                    ))}
                  </div>
                  {data.divergence.find((d) => d.attribute_name) && (
                    <div className="text-[11px] text-white/60 space-y-0.5 mt-1">
                      {data.divergence.filter((d) => d.attribute_name).map((d, i) => (
                        <div key={i}>
                          <span className="text-white/80">{d.attribute_name}:</span>{" "}
                          CMDB <span className="text-rose-300">{d.cmdb_value}</span> vs observed{" "}
                          <span className="text-emerald-300">{d.observed_value}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <p className="text-white/50 text-xs">No CMDB divergence recorded for this entity.</p>
              )}
            </section>

            {/* ── SECTION: Operational evidence (Abeyance Memory + T-VEC) ── */}
            <section className="space-y-3 pt-3 border-t border-cyan-900/30">
              <div className="flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-cyan-300" />
                <h4 className="text-[11px] uppercase tracking-wider text-white/70 font-bold">Operational evidence</h4>
              </div>
              <p className="text-[10px] text-white/40">Accumulated by Abeyance Memory · linked by T-VEC</p>

            {/* Embedding status */}
            <div className="flex items-center justify-between text-[11px] rounded-lg bg-[#06203b] border border-cyan-900/30 px-3 py-2">
              <span className="text-white/60">T-VEC coverage</span>
              <span className="flex items-center gap-2">
                {computing && <Loader2 className="w-3 h-3 animate-spin text-cyan-400" />}
                <span className={computing ? "text-cyan-300" : "text-white/80"}>
                  {data.embedded_count}/{data.fragment_count} embedded
                  {computing ? " — computing…" : ""}
                </span>
              </span>
            </div>

            {/* Snap "why" cards */}
            <div className="space-y-2">
              <p className="text-[10px] uppercase tracking-wider text-white/50 font-bold">
                Correlated evidence — what T-VEC links here ({data.snaps.length})
              </p>
              {data.snaps.length === 0 ? (
                <p className="text-white/50 text-xs">No correlated evidence yet.</p>
              ) : (
                data.snaps.map((s, i) => (
                  <div key={i} className="rounded-lg bg-[#06203b] border border-cyan-900/30 p-3 space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/80">
                        {s.relation_label}
                      </span>
                      <div className="flex items-center gap-2">
                        {s.rescored_live && (
                          <span className="inline-flex items-center gap-1 text-[10px] text-cyan-300" title="Scored against current T-VEC embeddings">
                            <Sparkles className="w-3 h-3" /> live
                          </span>
                        )}
                        {(() => {
                          const suf = sufficiency(s.dimensions);
                          return (
                            <span
                              title={`Scored on ${DIMENSIONS.filter((d) => s.dimensions[d.key] != null).length} of 5 dimensions`}
                              className={`inline-block px-1.5 py-0.5 rounded-full text-[10px] font-medium border ${suf.cls}`}
                            >
                              {suf.label}
                            </span>
                          );
                        })()}
                        <span className="text-sm font-bold text-white tabular-nums">{s.final_score.toFixed(3)}</span>
                      </div>
                    </div>
                    <p className="text-[12px] text-white/75 leading-snug line-clamp-2">
                      <ChevronRight className="w-3 h-3 inline text-cyan-400" /> {s.matched_snippet || "(no snippet)"}
                    </p>
                    <div className="space-y-1">
                      {DIMENSIONS.map((d) => (
                        <DimBar
                          key={d.key}
                          label={d.label}
                          icon={d.icon}
                          value={s.dimensions[d.key] ?? null}
                          dominant={s.dominant_driver === d.key}
                        />
                      ))}
                    </div>
                    <p className="text-[11px] text-white/55 italic">{s.why}</p>
                  </div>
                ))
              )}
            </div>

            {/* Evidence timeline */}
            <div className="space-y-2">
              <p className="text-[10px] uppercase tracking-wider text-white/50 font-bold">
                Evidence timeline ({data.evidence.length})
              </p>
              <div className="space-y-1.5">
                {data.evidence.map((e) => (
                  <div key={e.fragment_id} className="rounded-lg bg-[#06203b]/60 border border-cyan-900/20 px-3 py-2">
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${SNAP_STATUS_DOT[e.snap_status] ?? "bg-slate-500"}`} title={e.snap_status} />
                      <span className="font-mono text-white/70 px-1 rounded bg-white/5">{e.source_type}</span>
                      <span className="text-white/50">{fmtTime(e.event_timestamp)}</span>
                      <span
                        className={`ml-auto w-1.5 h-1.5 rounded-full ${e.embedded ? "bg-cyan-400" : "bg-slate-600"}`}
                        title={e.embedded ? "T-VEC embedded" : "not embedded"}
                      />
                    </div>
                    <p className="text-[11px] text-white/60 mt-1 line-clamp-2 leading-snug">{e.snippet}</p>
                  </div>
                ))}
              </div>
            </div>
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}
