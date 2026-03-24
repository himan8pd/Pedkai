"use client"

import React, { useEffect, useState } from 'react'
import { TrendingUp, AlertCircle, DollarSign, Zap, Info } from 'lucide-react'
import { useAuth } from '@/app/context/AuthContext'

export default function ROIDashboardPage() {
  const { token, authFetch } = useAuth()
  const [roiData, setRoiData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (token) fetchROIData()
  }, [token])

  const fetchROIData = async () => {
    try {
      setLoading(true)
      const response = await authFetch('/api/v1/autonomous/roi-dashboard')

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: Failed to fetch ROI dashboard`)
      }

      const data = await response.json()
      setRoiData(data)
      setError(null)
    } catch (err: any) {
      console.error('Error fetching ROI data:', err)
      setError(err.message || 'Failed to load ROI data')
      // No mock fallback — show error state only
      setRoiData(null)
    } finally {
      setLoading(false)
    }
  }

  const formatCurrency = (value: number | null | undefined) => {
    if (value === null || value === undefined) {
      return 'N/A'
    }
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency: 'GBP',
      maximumFractionDigits: 0,
    }).format(value)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen p-4">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-400 mx-auto mb-4"></div>
          <p className="text-white/60">Loading ROI Dashboard...</p>
        </div>
      </div>
    )
  }

  if (!roiData) {
    return (
      <div className="space-y-8 p-4 md:p-8">
        <div className="bg-red-900 border border-red-700 rounded-lg p-6">
          <h2 className="text-red-100 font-semibold mb-2">Error Loading ROI Data</h2>
          <p className="text-red-200 text-sm">{error}</p>
          <button
            onClick={fetchROIData}
            className="mt-4 px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded text-sm"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8 p-4 md:p-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">ROI Dashboard</h1>
        <p className="text-white/60">
          Business value metrics for 30-day period
        </p>
        <p className="text-white/50 text-sm mt-2">
          Period: {new Date(roiData.period_start).toLocaleDateString()} – {new Date(roiData.period_end).toLocaleDateString()}
        </p>
      </div>

      {/* Main KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Revenue Protected Card */}
        <div className="bg-[#0a2d4a] rounded-xl border border-[rgba(7,242,219,0.12)] p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white/80 font-semibold flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-green-400" />
              Revenue Protected
            </h3>
            {roiData.revenue_protected?.is_estimate && (
              <span className="bg-yellow-900 text-yellow-100 text-xs font-semibold px-2 py-1 rounded">
                ESTIMATE
              </span>
            )}
          </div>
          <p className="text-4xl font-bold text-white">
            {roiData.revenue_protected?.value ? formatCurrency(roiData.revenue_protected.value) : 'N/A'}
          </p>
          <p className="text-sm text-white/60 mt-2">
            Confidence: {roiData.revenue_protected?.confidence_interval || '±15%'}
          </p>
          {roiData.data_sources?.bss === 'mock' && (
            <p className="text-xs text-yellow-400 mt-3 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              Using mock BSS data. Real figures pending integration.
            </p>
          )}
        </div>

        {/* Incidents Prevented Card */}
        <div className="bg-[#0a2d4a] rounded-xl border border-[rgba(7,242,219,0.12)] p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white/80 font-semibold">Incidents Prevented</h3>
            <Zap className="w-5 h-5 text-blue-400" />
          </div>
          <p className="text-4xl font-bold text-white">{roiData.incidents_prevented || 0}</p>
          <p className="text-sm text-white/60 mt-2">
            via early detection & recommendation
          </p>
        </div>

        {/* MTTR Reduction Card */}
        <div className="bg-[#0a2d4a] rounded-xl border border-[rgba(7,242,219,0.12)] p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white/80 font-semibold">MTTR Reduction</h3>
            <TrendingUp className="w-5 h-5 text-green-400" />
          </div>
          <p className="text-4xl font-bold text-white">{roiData.mttr_reduction_pct || 0}%</p>
          <p className="text-sm text-white/60 mt-2">
            vs. non-Pedkai baseline
          </p>
        </div>
      </div>

      {/* MTTR Trend Chart — requires real time-series data from backend */}
      <div className="bg-[#0a2d4a] rounded-xl border border-[rgba(7,242,219,0.12)] p-6">
        <h2 className="text-xl font-bold text-white mb-4">MTTR Reduction Trend</h2>
        <div className="py-8 text-center">
          <p className="text-white/80 text-lg font-medium mb-2">No Trend Data Available</p>
          <p className="text-white/60 text-sm max-w-md mx-auto">
            MTTR trend visualization requires at least 7 days of incident resolution data.
            Trend data will populate automatically as incidents are processed.
          </p>
        </div>
      </div>

      {/* Methodology & Data Sources */}
      <div className="bg-[#0a2d4a] rounded-xl border border-[rgba(7,242,219,0.12)] p-6">
        <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
          <Info className="w-5 h-5" />
          Methodology & Data Sources
        </h2>
        <div className="space-y-4">
          <div>
            <h3 className="text-white/80 font-semibold mb-2">Calculation Method</h3>
            <p className="text-white/60 text-sm">
              All figures use a counterfactual methodology comparing Pedkai-managed zones vs. non-Pedkai baseline.
              See the full methodology document for details on confidence intervals, limitations, and audit trail.
            </p>
            <a
              href={roiData.methodology_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block mt-3 px-4 py-2 bg-cyan-400 hover:bg-cyan-300 text-gray-950 font-bold text-white rounded text-sm"
            >
              View Full Methodology
            </a>
          </div>

          <div className="border-t border-cyan-900/30 pt-4">
            <h3 className="text-white/80 font-semibold mb-2">Data Sources</h3>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div className="bg-[#06203b] rounded p-3">
                <p className="text-white/60">BSS Data</p>
                <p className="text-white font-semibold capitalize">
                  {roiData.data_sources?.bss || 'unknown'}
                </p>
              </div>
              <div className="bg-[#06203b] rounded p-3">
                <p className="text-white/60">KPI Data</p>
                <p className="text-white font-semibold capitalize">
                  {roiData.data_sources?.kpi || 'unknown'}
                </p>
              </div>
            </div>
          </div>

          {roiData.revenue_protected?.is_estimate && (
            <div className="bg-yellow-900 border border-yellow-700 rounded p-4">
              <p className="text-yellow-100 text-sm">
                <strong>Note:</strong> Revenue figures are estimates based on synthesized BSS data.
                Real revenue impact requires integration with live billing systems and post-deployment audit.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Governance Notice */}
      <div className="bg-blue-900 border border-blue-700 rounded-lg p-6">
        <h3 className="text-blue-100 font-semibold mb-2">Governance & Audit</h3>
        <p className="text-blue-200 text-sm">
          All value calculations are auditable and reproducible. For audit data exports, contact the Pedkai operations team.
          This dashboard complies with {roiData.data_sources?.bss === 'mock' ? 'interim' : 'full'} governance requirements.
        </p>
      </div>
    </div>
  )
}
