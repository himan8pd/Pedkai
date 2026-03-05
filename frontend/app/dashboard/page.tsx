"use client";

import React, { useEffect, useRef, useState } from "react";
import Dashboard from "@/app/components/Dashboard";
import { useAuth } from "@/app/context/AuthContext";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function DashboardPage() {
  const { tenantId, token } = useAuth();
  const [alarms, setAlarms] = useState<any[]>([]);
  const [selectedAlarm, setSelectedAlarm] = useState<any>(null);
  const [scorecard, setScorecard] = useState<any | null>(null);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const reconnectRef = useRef<number>(0);

  // Load initial scorecard via REST once auth token is available
  useEffect(() => {
    if (!token) return;
    async function loadInitial() {
      try {
        // Fetch scorecard using real auth token
        const scRes = await fetch(
          `${API_BASE_URL}/api/v1/autonomous/scorecard`,
          {
            headers: { Authorization: `Bearer ${token}` },
          },
        ).catch(() => null);
        if (scRes && scRes.ok) {
          const scData = await scRes.json();
          setScorecard(scData);
        }
      } catch (e) {
        console.warn("Initial data load error:", e);
      }
    }
    loadInitial();
  }, [token]);

  // Connect to SSE with exponential backoff reconnection
  useEffect(() => {
    if (!tenantId) return;

    function connect() {
      // Close existing
      if (esRef.current) {
        try {
          esRef.current.close();
        } catch (e) {}
        esRef.current = null;
      }

      const es = new EventSource(
        `${API_BASE_URL}/api/v1/stream/alarms?tenant_id=${encodeURIComponent(tenantId)}`,
      );
      esRef.current = es;

      es.onopen = () => {
        setConnected(true);
        reconnectRef.current = 0;
      };

      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.event === "alarms_updated") {
            // Use real alarm objects if provided, otherwise show count placeholder
            if (data.alarms && Array.isArray(data.alarms)) {
              setAlarms(data.alarms);
            }
            // Update scorecard with alarm count
            setScorecard((prev: any) => ({
              ...(prev || {}),
              active_alarms: data.count,
              avg_mttr: prev?.avg_mttr ?? 12.4,
              uptime_pct: prev?.uptime_pct ?? 99.2,
            }));
          }
        } catch (e) {
          console.warn("SSE parse error", e);
        }
      };

      es.onerror = (err) => {
        setConnected(false);
        try {
          es.close();
        } catch (e) {}
        // Backoff reconnect
        reconnectRef.current = Math.min(
          60,
          (reconnectRef.current || 1) * 2 || 1,
        );
        const wait = reconnectRef.current * 1000;
        setTimeout(() => connect(), wait);
      };
    }

    connect();

    return () => {
      if (esRef.current) {
        try {
          esRef.current.close();
        } catch (e) {}
        esRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId]);

  return (
    <div className="p-4 md:p-8">
      <div className="mb-4 text-sm text-gray-400">
        SSE: {connected ? "connected" : "disconnected"}
      </div>
      <Dashboard
        token={token}
        alarms={alarms}
        selectedAlarm={selectedAlarm}
        onSelectAlarm={(a) => setSelectedAlarm(a)}
        onAcknowledge={(id) => {
          setAlarms((current) =>
            current.map((alarm) =>
              alarm.id === id ? { ...alarm, ackState: "acknowledged" } : alarm,
            ),
          );
          setSelectedAlarm((current: any) =>
            current?.id === id
              ? { ...current, ackState: "acknowledged" }
              : current,
          );
        }}
        scorecard={scorecard}
      />
    </div>
  );
}
