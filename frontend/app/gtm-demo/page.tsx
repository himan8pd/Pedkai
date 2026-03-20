"use client"

import { useMemo, useState } from "react"
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Database,
  GitBranch,
  ShieldCheck,
  TrendingUp,
} from "lucide-react"

type DemoAct = "blind-spot" | "reconciliation" | "impact"

const INCIDENTS = [
  {
    id: "INC-44021",
    title: "Payment ingress latency spike",
    cmdbStatus: "healthy",
    telemetryStatus: "degraded",
    severity: "critical",
  },
  {
    id: "INC-44037",
    title: "Session broker packet loss",
    cmdbStatus: "unknown",
    telemetryStatus: "impaired",
    severity: "major",
  },
  {
    id: "INC-44058",
    title: "Policy gateway restart chain",
    cmdbStatus: "healthy",
    telemetryStatus: "unstable",
    severity: "critical",
  },
]

const EVIDENCE_FLOW = [
  {
    step: "Intent",
    detail: "Datagerry CMDB shows no relation between edge firewall and session broker.",
    confidence: "0.41",
  },
  {
    step: "Reality",
    detail: "Telemetry indicates synchronized jitter and restart ripple across both nodes.",
    confidence: "0.68",
  },
  {
    step: "Memory",
    detail: "Prior incident note references maintenance bridge connecting both systems.",
    confidence: "0.83",
  },
  {
    step: "Corroboration",
    detail: "Design attachment + change ticket align with inferred dependency.",
    confidence: "0.94",
  },
]

const ROI_DELTA = [
  { label: "CMDB Drift Resolved", before: "14.2%", after: "2.1%" },
  { label: "Time to Causal Clarity", before: "48 min", after: "11 min" },
  { label: "Unsafe Actions Prevented", before: "n/a", after: "7 blocked" },
  { label: "Incident Cost Exposure", before: "$180k", after: "$62k" },
]

export default function GTMDemoPage() {
  const [act, setAct] = useState<DemoAct>("blind-spot")

  const summary = useMemo(() => {
    if (act === "blind-spot") {
      return {
        headline: "Fragmented memory creates operational blindness",
        sub: "Intent and reality disagree across the same incident stream.",
      }
    }

    if (act === "reconciliation") {
      return {
        headline: "Pedkai validates hidden dependencies before trust",
        sub: "Dark Graph edges appear only after multi-modal corroboration.",
      }
    }

    return {
      headline: "Policy-safe intelligence drives measurable outcomes",
      sub: "Operational risk drops while existing tools remain in place.",
    }
  }, [act])

  return (
    <main className="min-h-screen bg-[#030f26] text-white p-6 md:p-10">
      <div className="max-w-7xl mx-auto space-y-8">
        <header className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-300">
            <TrendingUp className="h-3.5 w-3.5" />
            Pedkai GTM Demo Suite
          </div>
          <h1 className="text-3xl md:text-5xl font-semibold tracking-tight">
            AI-Native Operational Reconciliation Engine
          </h1>
          <p className="text-slate-300 max-w-3xl">
            A guided story from CMDB blind spots to confidence-scored remediation with policy guardrails.
          </p>
        </header>

        <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <button
            onClick={() => setAct("blind-spot")}
            className={`glass rounded-xl p-4 text-left transition ${
              act === "blind-spot" ? "ring-2 ring-rose-400/60" : "hover:ring-1 hover:ring-white/20"
            }`}
          >
            <div className="flex items-center gap-2 text-rose-300 text-sm mb-1">
              <AlertTriangle className="h-4 w-4" />
              Act 1
            </div>
            <p className="font-medium">The Blind Spot</p>
            <p className="text-sm text-slate-400">Intent and reality conflict in live operations.</p>
          </button>

          <button
            onClick={() => setAct("reconciliation")}
            className={`glass rounded-xl p-4 text-left transition ${
              act === "reconciliation" ? "ring-2 ring-cyan-400/60" : "hover:ring-1 hover:ring-white/20"
            }`}
          >
            <div className="flex items-center gap-2 text-cyan-300 text-sm mb-1">
              <GitBranch className="h-4 w-4" />
              Act 2
            </div>
            <p className="font-medium">The Reconciliation</p>
            <p className="text-sm text-slate-400">Dark Graph inference backed by corroboration.</p>
          </button>

          <button
            onClick={() => setAct("impact")}
            className={`glass rounded-xl p-4 text-left transition ${
              act === "impact" ? "ring-2 ring-emerald-400/60" : "hover:ring-1 hover:ring-white/20"
            }`}
          >
            <div className="flex items-center gap-2 text-emerald-300 text-sm mb-1">
              <ShieldCheck className="h-4 w-4" />
              Act 3
            </div>
            <p className="font-medium">The Business Impact</p>
            <p className="text-sm text-slate-400">Policy-safe recommendations and ROI delta.</p>
          </button>
        </section>

        <section className="glass rounded-2xl p-5 md:p-7 border border-[rgba(7,242,219,0.1)] space-y-3">
          <h2 className="text-2xl font-semibold">{summary.headline}</h2>
          <p className="text-slate-300">{summary.sub}</p>
          <div className="flex flex-wrap gap-2 text-xs text-slate-300 pt-1">
            <span className="rounded-full bg-[#0a2d4a]/60 px-3 py-1 border border-cyan-900/30">Dataset: CasinoLimit simulation</span>
            <span className="rounded-full bg-[#0a2d4a]/60 px-3 py-1 border border-cyan-900/30">CMDB: Datagerry seeded with 700+ CIs</span>
            <span className="rounded-full bg-[#0a2d4a]/60 px-3 py-1 border border-cyan-900/30">Output: Living Context Graph findings</span>
          </div>
        </section>

        {act === "blind-spot" && (
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <article className="glass rounded-2xl p-5 border border-[rgba(7,242,219,0.1)]">
              <h3 className="text-lg font-semibold mb-4">Incident Contradictions</h3>
              <div className="space-y-3">
                {INCIDENTS.map((incident) => (
                  <div key={incident.id} className="rounded-xl border border-[rgba(7,242,219,0.1)] bg-[#0a2d4a]/70 p-4">
                    <div className="flex items-center justify-between">
                      <p className="font-medium">{incident.id}</p>
                      <span className={`text-xs px-2 py-1 rounded-full ${incident.severity === "critical" ? "bg-rose-400/20 text-rose-300" : "bg-amber-300/20 text-amber-200"}`}>
                        {incident.severity}
                      </span>
                    </div>
                    <p className="text-sm text-slate-300 mt-1">{incident.title}</p>
                    <div className="grid grid-cols-2 gap-3 mt-3 text-sm">
                      <div className="rounded-lg border border-cyan-900/30 bg-[#06203b] p-2">
                        <p className="text-slate-400">CMDB Intent</p>
                        <p className="text-cyan-300">{incident.cmdbStatus}</p>
                      </div>
                      <div className="rounded-lg border border-cyan-900/30 bg-[#06203b] p-2">
                        <p className="text-slate-400">Telemetry Reality</p>
                        <p className="text-rose-300">{incident.telemetryStatus}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </article>

            <article className="glass rounded-2xl p-5 border border-[rgba(7,242,219,0.1)]">
              <h3 className="text-lg font-semibold mb-4">What Operators Experience</h3>
              <ul className="space-y-3 text-sm text-slate-300">
                <li className="rounded-xl border border-[rgba(7,242,219,0.1)] bg-[#0a2d4a]/70 p-3">Conflicting systems force manual cross-referencing across tickets, CMDB, and telemetry.</li>
                <li className="rounded-xl border border-[rgba(7,242,219,0.1)] bg-[#0a2d4a]/70 p-3">False assumptions lead to prolonged triage and repeated escalations.</li>
                <li className="rounded-xl border border-[rgba(7,242,219,0.1)] bg-[#0a2d4a]/70 p-3">Decision confidence remains low because dependency truth is incomplete.</li>
              </ul>
            </article>
          </section>
        )}

        {act === "reconciliation" && (
          <section className="grid grid-cols-1 lg:grid-cols-5 gap-6">
            <article className="lg:col-span-3 glass rounded-2xl p-5 border border-[rgba(7,242,219,0.1)]">
              <h3 className="text-lg font-semibold mb-4">Evidence Corroboration Timeline</h3>
              <div className="space-y-3">
                {EVIDENCE_FLOW.map((item, index) => (
                  <div key={item.step} className="rounded-xl border border-[rgba(7,242,219,0.1)] bg-[#0a2d4a]/70 p-4 flex items-start gap-3">
                    <div className="mt-0.5 rounded-full bg-cyan-500/20 text-cyan-300 h-7 w-7 grid place-items-center text-xs">
                      {index + 1}
                    </div>
                    <div className="space-y-1">
                      <p className="font-medium">{item.step}</p>
                      <p className="text-sm text-slate-300">{item.detail}</p>
                      <p className="text-xs text-emerald-300">Confidence: {item.confidence}</p>
                    </div>
                  </div>
                ))}
              </div>
            </article>

            <article className="lg:col-span-2 glass rounded-2xl p-5 border border-[rgba(7,242,219,0.1)] space-y-4">
              <h3 className="text-lg font-semibold">Engine Guarantees</h3>
              <div className="rounded-xl border border-[rgba(7,242,219,0.1)] bg-[#0a2d4a]/70 p-4">
                <div className="flex items-center gap-2 text-cyan-300 mb-2">
                  <Database className="h-4 w-4" />
                  Multi-Source Validation
                </div>
                <p className="text-sm text-slate-300">No latent edge is accepted from correlation alone.</p>
              </div>
              <div className="rounded-xl border border-[rgba(7,242,219,0.1)] bg-[#0a2d4a]/70 p-4">
                <div className="flex items-center gap-2 text-violet-300 mb-2">
                  <Brain className="h-4 w-4" />
                  Abeyance Memory
                </div>
                <p className="text-sm text-slate-300">Partial clues are retained and re-evaluated when supporting evidence arrives.</p>
              </div>
              <div className="rounded-xl border border-[rgba(7,242,219,0.1)] bg-[#0a2d4a]/70 p-4">
                <div className="flex items-center gap-2 text-emerald-300 mb-2">
                  <ShieldCheck className="h-4 w-4" />
                  Policy Constitution
                </div>
                <p className="text-sm text-slate-300">Low-confidence or high-risk paths are blocked before operator exposure.</p>
              </div>
            </article>
          </section>
        )}

        {act === "impact" && (
          <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {ROI_DELTA.map((metric) => (
              <article key={metric.label} className="glass rounded-2xl p-5 border border-[rgba(7,242,219,0.1)]">
                <p className="text-sm text-slate-400">{metric.label}</p>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-xl border border-cyan-900/30 bg-[#0a2d4a]/80 p-3">
                    <p className="text-white/50">Before</p>
                    <p className="text-rose-300 text-lg font-medium">{metric.before}</p>
                  </div>
                  <div className="rounded-xl border border-cyan-900/30 bg-[#0a2d4a]/80 p-3">
                    <p className="text-white/50">After</p>
                    <p className="text-emerald-300 text-lg font-medium">{metric.after}</p>
                  </div>
                </div>
              </article>
            ))}

            <article className="lg:col-span-3 glass rounded-2xl p-5 border border-[rgba(7,242,219,0.1)]">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="h-5 w-5 text-emerald-300 mt-0.5" />
                <div>
                  <h3 className="text-lg font-semibold">Executive Summary</h3>
                  <p className="text-slate-300 mt-1">
                    Pedkai delivers measurable trust recovery without replacing existing ITSM or CMDB investments. It reconciles contradictory sources, explains why recommendations are safe, and gives operations teams faster paths to confident action.
                  </p>
                </div>
              </div>
            </article>
          </section>
        )}
      </div>
    </main>
  )
}
