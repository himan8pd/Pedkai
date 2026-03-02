"use client"

import React, { useEffect, useState } from 'react'
import {
  TrendingUp, TrendingDown, AlertCircle, Shield, Activity, Clock,
  ChevronDown, ChevronUp, BarChart3, Target, Zap
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/app/context/AuthContext'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'

interface ScorecardData {
  pedkai_zone_mttr_minutes: number | null
  pedkai_zone_incident_count: number
  non_pedkai_zone_mttr_minutes: number | null
  non_pedkai_zone_incident_count: number | null
  improvement_pct: number | null
  period_start: string
  period_end: string
  value_protected: {
    revenue_protected: number | null
    incidents_prevented: number | null
    uptime_gained_minutes: number | null
    methodology_doc_url: string
    confidence_interval: string | null
  }
  baseline_status: string | null
  baseline_note: string | null
  drift_calibration: any
}

interface Detection {
  entity_id: string
  entity_name: string
  metric_name: string
  current_value: number
  baseline_value: number
  drift_pct: number
  severity: string
  recommendation: string
  ai_generated: boolean
  ai_watermark: string
}

interface ValueCapture {
  revenue_protected: number
  incidents_prevented: number
  uptime_gained_minutes: number
}

function KpiCard({
  label, value, subtitle, icon, trend, color = 'blue'
}: {
  label: string; value: string; subtitle?: string; icon: React.ReactNode; trend?: 'up' | 'down' | null; color?: string
}) {
  const colorMap: Record<string, string> = {
    blue: 'from-blue-500/20 to-blue-600/5 border-blue-500/30',
    green: 'from-emerald-500/20 to-emerald-600/5 border-emerald-500/30',
    amber: 'from-amber-500/20 to-amber-600/5 border-amber-500/30',
    red: 'from-red-500/20 to-red-600/5 border-red-500/30',
    purple: 'from-purple-500/20 to-purple-600/5 border-purple-500/30',
    cyan: 'from-cyan-500/20 to-cyan-600/5 border-cyan-500/30',
  }
  return (
    <div className={cn(
      "rounded-xl border p-5 bg-gradient-to-br transition-all hover:scale-[1.02]",
      colorMap[color] || colorMap.blue
    )}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">{label}</h3>
        <div className="text-gray-400">{icon}</div>
      </div>
      <p className="text-3xl font-bold text-white">{value}</p>
      {subtitle && (
        <div className="flex items-center gap-1 mt-2">
          {trend === 'up' && <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />}
          {trend === 'down' && <TrendingDown className="w-3.5 h-3.5 text-red-400" />}
          <p className="text-sm text-gray-400">{subtitle}</p>
        </div>
      )}
    </div>
  )
}

export default function ScorecardPage() {
  const { token } = useAuth()
  const [scorecard, setScorecard] = useState<ScorecardData | null>(null)
  const [detections, setDetections] = useState<Detection[]>([])
  const [valueCapture, setValueCapture] = useState<ValueCapture | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showDetections, setShowDetections] = useState(true)
  const [showMethodology, setShowMethodology] = useState(false)

  useEffect(() => {
    async function fetchAll() {
      if (!token) return
      const headers = { Authorization: `Bearer ${token}` }

      try {
        const [scRes, detRes, valRes] = await Promise.allSettled([
          fetch(`${API_BASE_URL}/api/v1/autonomous/scorecard`, { headers }),
          fetch(`${API_BASE_URL}/api/v1/autonomous/detections`, { headers }),
          fetch(`${API_BASE_URL}/api/v1/autonomous/value-capture`, { headers }),
        ])

        if (scRes.status === 'fulfilled' && scRes.value.ok) {
          setScorecard(await scRes.value.json())
        }
        if (detRes.status === 'fulfilled' && detRes.value.ok) {
          setDetections(await detRes.value.json())
        }
        if (valRes.status === 'fulfilled' && valRes.value.ok) {
          setValueCapture(await valRes.value.json())
        }
      } catch (e: any) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    fetchAll()
  }, [token])

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-gray-400 animate-pulse text-lg">Loading scorecard...</div>
    </div>
  )

  return (
    <div className="space-y-8 p-4 md:p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-1">AI Scorecard</h1>
        <p className="text-gray-400">
          Autonomous intelligence performance &middot;{' '}
          {scorecard ? (
            <>
              {new Date(scorecard.period_start).toLocaleDateString()} &ndash;{' '}
              {new Date(scorecard.period_end).toLocaleDateString()}
            </>
          ) : 'Last 30 days'}
        </p>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-red-900/30 border border-red-700 text-red-300 text-sm">{error}</div>
      )}

      {/* Primary KPI Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        <KpiCard
          label="Mean Time to Resolve"
          value={scorecard?.pedkai_zone_mttr_minutes != null ? `${scorecard.pedkai_zone_mttr_minutes} min` : 'Pending'}
          subtitle={scorecard?.pedkai_zone_mttr_minutes != null ? 'Pedkai-managed zone' : 'No closed incidents yet'}
          icon={<Clock className="w-5 h-5" />}
          trend={scorecard?.pedkai_zone_mttr_minutes != null ? 'down' : null}
          color="cyan"
        />
        <KpiCard
          label="Incidents Tracked"
          value={String(scorecard?.pedkai_zone_incident_count ?? 0)}
          subtitle="Active monitoring window (30d)"
          icon={<AlertCircle className="w-5 h-5" />}
          color="amber"
        />
        <KpiCard
          label="Drift Detections"
          value={String(detections.length)}
          subtitle="KPI anomalies flagged"
          icon={<Activity className="w-5 h-5" />}
          color="purple"
        />
        <KpiCard
          label="Revenue Protected"
          value={valueCapture?.revenue_protected != null ? `$${(valueCapture.revenue_protected / 1000).toFixed(0)}K` : 'N/A'}
          subtitle={valueCapture ? 'Based on closed incidents' : 'Awaiting incident closure'}
          icon={<Target className="w-5 h-5" />}
          trend={valueCapture?.revenue_protected ? 'up' : null}
          color="green"
        />
        <KpiCard
          label="Incidents Prevented"
          value={String(valueCapture?.incidents_prevented ?? '—')}
          subtitle="Proactive shield interventions"
          icon={<Shield className="w-5 h-5" />}
          color="blue"
        />
        <KpiCard
          label="Uptime Recovered"
          value={valueCapture?.uptime_gained_minutes != null ? `${valueCapture.uptime_gained_minutes.toFixed(0)} min` : '—'}
          subtitle="From automated resolution"
          icon={<Zap className="w-5 h-5" />}
          color="green"
        />
      </div>

      {/* Baseline Status */}
      {scorecard?.baseline_status === 'pending_shadow_mode_collection' && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-5">
          <div className="flex items-start gap-3">
            <BarChart3 className="w-5 h-5 text-amber-400 mt-0.5 shrink-0" />
            <div>
              <h3 className="text-amber-300 font-semibold text-sm">Counterfactual Baseline Pending</h3>
              <p className="text-gray-400 text-sm mt-1">{scorecard.baseline_note}</p>
              <p className="text-gray-500 text-xs mt-2">
                Non-Pedkai zone comparison will be available after 30-day shadow-mode deployment.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Drift Calibration */}
      {scorecard?.drift_calibration && !scorecard.drift_calibration.error && (
        <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-5">
          <h3 className="text-white font-semibold mb-3 flex items-center gap-2">
            <Activity className="w-4 h-4 text-purple-400" />
            Drift Calibration
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Object.entries(scorecard.drift_calibration).map(([key, val]) => (
              <div key={key}>
                <p className="text-xs text-gray-500 uppercase tracking-wider">{key.replace(/_/g, ' ')}</p>
                <p className="text-white font-mono text-sm mt-1">{typeof val === 'number' ? val.toFixed(3) : String(val)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* KPI Drift Detections */}
      <div className="rounded-xl border border-gray-700 bg-gray-800/50 overflow-hidden">
        <button
          onClick={() => setShowDetections(!showDetections)}
          className="w-full px-5 py-4 flex items-center justify-between hover:bg-gray-800 transition-colors"
        >
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Shield className="w-5 h-5 text-cyan-400" />
            Autonomous Shield Detections
            <span className="text-sm font-normal text-gray-400">({detections.length})</span>
          </h2>
          {showDetections ? <ChevronUp className="w-5 h-5 text-gray-400" /> : <ChevronDown className="w-5 h-5 text-gray-400" />}
        </button>

        {showDetections && (
          <div className="border-t border-gray-700">
            {detections.length === 0 ? (
              <div className="p-6 text-center text-gray-500">No drift detections in current window</div>
            ) : (
              <div className="divide-y divide-gray-700/50">
                {detections.map((det, idx) => (
                  <div key={idx} className="px-5 py-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-white font-medium">{det.entity_name}</p>
                        <p className="text-sm text-gray-400 mt-0.5">
                          {det.metric_name}: <span className="text-white font-mono">{det.current_value.toFixed(2)}</span>
                          {' '}(baseline: {det.baseline_value.toFixed(2)})
                        </p>
                      </div>
                      <span className={cn(
                        "px-2 py-1 rounded text-xs font-bold uppercase",
                        det.severity === 'high' ? 'bg-red-900/50 text-red-300' :
                        det.severity === 'medium' ? 'bg-amber-900/50 text-amber-300' :
                        'bg-gray-700 text-gray-300'
                      )}>
                        {det.severity}
                      </span>
                    </div>
                    {det.recommendation && (
                      <p className="text-sm text-cyan-400/80 mt-2 italic">&quot;{det.recommendation}&quot;</p>
                    )}
                    {det.ai_generated && (
                      <span className="inline-flex items-center gap-1 mt-2 text-[10px] text-amber-500/60 uppercase tracking-wider">
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
      <div className="rounded-xl border border-gray-700 bg-gray-800/30 p-5">
        <button
          onClick={() => setShowMethodology(!showMethodology)}
          className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors"
        >
          {showMethodology ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          Methodology & Data Sources
        </button>
        {showMethodology && (
          <div className="mt-3 text-sm text-gray-500 space-y-2">
            <p>MTTR is calculated from actual incident created_at → closed_at timestamps in PostgreSQL.</p>
            <p>Revenue protection uses policy-engine derived risk parameters per incident severity tier.</p>
            <p>Drift detections use Z-score analysis against rolling KPI baselines from TimescaleDB.</p>
            <p>Non-Pedkai zone comparison requires 30-day shadow-mode data (not yet collected).</p>
            <p className="text-gray-600">
              Full methodology: <span className="font-mono text-xs">/docs/value_methodology.md</span>
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
