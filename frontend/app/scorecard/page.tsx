"use client"

import React from 'react'
import { TrendingUp, AlertCircle } from 'lucide-react'

export default function ScorecardPage() {
  const [scorecard, setScorecard] = React.useState<any>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    // Fetch scorecard data from API
    setLoading(false)
  }, [])

  return (
    <div className="space-y-8 p-4 md:p-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">AI Scorecard</h1>
        <p className="text-gray-400">Platform performance and autonomous intelligence metrics</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* KPI Cards */}
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-gray-300 font-semibold">Avg MTTR</h3>
            <TrendingUp className="w-5 h-5 text-green-400" />
          </div>
          <p className="text-3xl font-bold text-white">12.5 min</p>
          <p className="text-sm text-gray-400 mt-2">↓ 8% vs last week</p>
        </div>

        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-gray-300 font-semibold">Uptime</h3>
            <TrendingUp className="w-5 h-5 text-green-400" />
          </div>
          <p className="text-3xl font-bold text-white">99.98%</p>
          <p className="text-sm text-gray-400 mt-2">↑ 0.02% vs last week</p>
        </div>

        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-gray-300 font-semibold">Decision Accuracy</h3>
            <AlertCircle className="w-5 h-5 text-blue-400" />
          </div>
          <p className="text-3xl font-bold text-white">94.2%</p>
          <p className="text-sm text-gray-400 mt-2">Based on 1,234 decisions</p>
        </div>

        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-gray-300 font-semibold">Revenue Protected</h3>
            <TrendingUp className="w-5 h-5 text-green-400" />
          </div>
          <p className="text-3xl font-bold text-white">$2.3M</p>
          <p className="text-sm text-gray-400 mt-2">This month</p>
        </div>

        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-gray-300 font-semibold">Automated Actions</h3>
            <TrendingUp className="w-5 h-5 text-green-400" />
          </div>
          <p className="text-3xl font-bold text-white">847</p>
          <p className="text-sm text-gray-400 mt-2">+12% vs last week</p>
        </div>

        <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-gray-300 font-semibold">Calibrated Confidence</h3>
            <AlertCircle className="w-5 h-5 text-blue-400" />
          </div>
          <p className="text-3xl font-bold text-white">87.4%</p>
          <p className="text-sm text-gray-400 mt-2">Empirically calibrated via feedback</p>
        </div>
      </div>

      {/* Trends Section */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-6">
        <h2 className="text-xl font-bold text-white mb-4">Performance Trends</h2>
        <div className="h-64 flex items-center justify-center text-gray-400">
          <p>Chart placeholder (integrate Chart.js or similar)</p>
        </div>
      </div>
    </div>
  )
}
