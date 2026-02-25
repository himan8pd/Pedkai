"use client"

import React, { useState } from 'react'
import { AlertCircle, Zap } from 'lucide-react'
import StatCard from '@/app/components/StatCard'
import AlarmCard from '@/app/components/AlarmCard'
import SitrepPanel from '@/app/components/SitrepPanel'

interface DashboardProps {
  token: string
  alarms: any[]
  selectedAlarm: any
  onSelectAlarm: (alarm: any) => void
  scorecard: any
}

export default function Dashboard({
  token,
  alarms,
  selectedAlarm,
  onSelectAlarm,
  scorecard,
}: DashboardProps) {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">NOC Dashboard</h1>
        <p className="text-gray-400">Real-time network operations center</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          title="Active Alarms"
          value={alarms.length}
          unit="events"
          icon={<AlertCircle className="w-6 h-6" />}
          trend={alarms.length > 10 ? 'up' : 'down'}
        />
        <StatCard
          title="Avg MTTR"
          value={scorecard?.avg_mttr ?? 'N/A'}
          unit="minutes"
          icon={<Zap className="w-6 h-6" />}
        />
        <StatCard
          title="Uptime"
          value={scorecard?.uptime_pct ?? 'N/A'}
          unit="%"
          icon={<AlertCircle className="w-6 h-6" />}
        />
        <StatCard
          title="SLA Score"
          value="98.5"
          unit="%"
          icon={<AlertCircle className="w-6 h-6" />}
        />
      </div>

      {/* Alarms + SITREP Side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Alarm Feed */}
        <div className="lg:col-span-2 space-y-4">
          <h2 className="text-xl font-bold text-white">Alarm Feed</h2>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {alarms.length === 0 ? (
              <div className="text-center py-8 text-gray-400">
                No active alarms
              </div>
            ) : (
              alarms.map((alarm) => (
                <AlarmCard
                  key={alarm.id}
                  alarm={alarm}
                  isSelected={selectedAlarm?.id === alarm.id}
                  onSelect={() => onSelectAlarm(alarm)}
                />
              ))
            )}
          </div>
        </div>

        {/* SITREP Panel */}
        <div>
          <h2 className="text-xl font-bold text-white mb-4">AI SITREP</h2>
          <SitrepPanel alarm={selectedAlarm} />
        </div>
      </div>
    </div>
  )
}
