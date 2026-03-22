"use client"

import React, { useState } from 'react'
import { AlertCircle, Zap } from 'lucide-react'
import StatCard from '@/app/components/StatCard'
import AlarmCard from '@/app/components/AlarmCard'
import SitrepPanel from '@/app/components/SitrepPanel'
import DataHealthPanel from '@/app/components/DataHealthPanel'

interface DashboardProps {
  token: string
  alarms: any[]
  selectedAlarm: any
  onSelectAlarm: (alarm: any) => void
  onAcknowledge: (id: string) => void
  scorecard: any
  onRefetchData?: () => void
}

export default function Dashboard({
  token,
  alarms,
  selectedAlarm,
  onSelectAlarm,
  onAcknowledge,
  scorecard,
  onRefetchData,
}: DashboardProps) {
  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-1">NOC Dashboard</h1>
        <p className="text-white/60">Real-time network operations center</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          label="Active Alarms"
          value={`${alarms.length} events`}
          icon={<AlertCircle className="w-6 h-6" />}
        />
        <StatCard
          label="Avg MTTR"
          value={scorecard?.avg_mttr ? `${scorecard.avg_mttr} minutes` : 'N/A'}
          icon={<Zap className="w-6 h-6" />}
        />
        <StatCard
          label="Uptime"
          value={scorecard?.uptime_pct ? `${scorecard.uptime_pct}%` : 'N/A'}
          icon={<AlertCircle className="w-6 h-6" />}
        />
        <StatCard
          label="SLA Score"
          value={scorecard?.sla_score ? `${scorecard.sla_score}%` : 'No Data'}
          icon={<AlertCircle className="w-6 h-6" />}
        />
      </div>

      {/* Alarms + SITREP Side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Alarm Feed — narrower column */}
        <div className="lg:col-span-2 space-y-4">
          <h2 className="text-xl font-bold text-white">Alarm Feed</h2>
          <div className="space-y-2 max-h-[600px] overflow-y-auto custom-scrollbar">
            {alarms.length === 0 ? (
              <div className="text-center py-8 text-white">
                No active alarms
              </div>
            ) : (
              alarms.map((alarm) => (
                <AlarmCard
                  key={alarm.id}
                  alarm={alarm}
                  isSelected={selectedAlarm?.id === alarm.id}
                  onClick={() => onSelectAlarm(alarm)}
                />
              ))
            )}
          </div>
        </div>

        {/* SITREP Panel — wider column */}
        <div className="lg:col-span-3">
          <h2 className="text-xl font-bold text-white mb-4">AI SITREP</h2>
          <SitrepPanel selectedAlarm={selectedAlarm} onAcknowledge={onAcknowledge} />
        </div>
      </div>

      {/* Tenant Data Health */}
      <DataHealthPanel onIngestionComplete={onRefetchData} />
    </div>
  )
}
