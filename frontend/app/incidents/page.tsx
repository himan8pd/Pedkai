"use client"

import React from 'react'
import { AlertCircle, Clock } from 'lucide-react'

export default function IncidentsPage() {
  const [incidents, setIncidents] = React.useState<any[]>([])
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    // Fetch incidents from API
    setLoading(false)
  }, [])

  return (
    <div className="space-y-8 p-4 md:p-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Incidents</h1>
        <p className="text-gray-400">Track and manage network incidents</p>
      </div>

      <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-900 border-b border-gray-700">
            <tr>
              <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">ID</th>
              <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Entity</th>
              <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Severity</th>
              <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Status</th>
              <th className="px-6 py-3 text-left text-sm font-semibold text-gray-300">Created</th>
            </tr>
          </thead>
          <tbody>
            {incidents.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-gray-400">
                  No incidents
                </td>
              </tr>
            ) : (
              incidents.map((incident) => (
                <tr key={incident.id} className="border-b border-gray-700 hover:bg-gray-700">
                  <td className="px-6 py-4 text-sm text-gray-300">{incident.id}</td>
                  <td className="px-6 py-4 text-sm text-gray-300">{incident.entity}</td>
                  <td className="px-6 py-4 text-sm">
                    <span className={`px-2 py-1 rounded text-xs font-semibold ${
                      incident.severity === 'critical' ? 'bg-red-900 text-red-200' :
                      incident.severity === 'major' ? 'bg-orange-900 text-orange-200' :
                      'bg-yellow-900 text-yellow-200'
                    }`}>
                      {incident.severity}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-300">{incident.status}</td>
                  <td className="px-6 py-4 text-sm text-gray-300">{incident.created}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
