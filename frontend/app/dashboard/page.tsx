"use client"

import React, { useEffect, useRef, useState } from 'react'
import Dashboard from '@/app/components/Dashboard'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'

export default function DashboardPage() {
  const [alarms, setAlarms] = useState<any[]>([])
  const [selectedAlarm, setSelectedAlarm] = useState<any>(null)
  const [scorecard, setScorecard] = useState<any | null>(null)
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)
  const reconnectRef = useRef<number>(0)

  // Simple function to synthesize alarms when SSE payload contains only counts
  const synthesizeAlarmsFromPayload = (payload: any) => {
    const count = payload.count ?? 1
    const tenant = payload.tenant_id ?? 'unknown'
    const now = new Date().toISOString()
    const generated = Array.from({ length: Math.min(count, 20) }).map((_, i) => ({
      id: `${payload.timestamp || now}-${i}`,
      specificProblem: `Generated alarm ${i + 1}`,
      perceivedSeverity: i % 3 === 0 ? 'critical' : 'major',
      alarmedObject: { id: `entity-${i + 1}` },
      eventTime: now,
      tenant_id: tenant,
    }))
    return generated
  }

  // Connect to SSE with exponential backoff reconnection
  useEffect(() => {
    function connect() {
      // Close existing
      if (esRef.current) {
        try { esRef.current.close() } catch (e) {}
        esRef.current = null
      }

      const es = new EventSource(`${API_BASE_URL}/api/v1/stream/alarms`)
      esRef.current = es

      es.onopen = () => {
        setConnected(true)
        reconnectRef.current = 0
      }

      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data)
          if (data.event === 'alarms_updated') {
            // If backend provides only counts, synthesize placeholder alarms
            const items = synthesizeAlarmsFromPayload(data)
            setAlarms(items)
            // Optionally refresh scorecard placeholder
            setScorecard({ avg_mttr: 12.4, uptime_pct: 99.2 })
          }
        } catch (e) {
          console.warn('SSE parse error', e)
        }
      }

      es.onerror = (err) => {
        setConnected(false)
        try { es.close() } catch (e) {}
        // Backoff reconnect
        reconnectRef.current = Math.min(60, (reconnectRef.current || 1) * 2 || 1)
        const wait = reconnectRef.current * 1000
        setTimeout(() => connect(), wait)
      }
    }

    connect()

    return () => {
      if (esRef.current) {
        try { esRef.current.close() } catch (e) {}
        esRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="p-4 md:p-8">
      <div className="mb-4 text-sm text-gray-400">SSE: {connected ? 'connected' : 'disconnected'}</div>
      <Dashboard
        token={''}
        alarms={alarms}
        selectedAlarm={selectedAlarm}
        onSelectAlarm={(a) => setSelectedAlarm(a)}
        scorecard={scorecard}
      />
    </div>
  )
}
