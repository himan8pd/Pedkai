"use client";

import React, { useState, useEffect } from 'react';
import { Database, AlertTriangle, Users, Activity, GitCompare, Loader2, Play, Network, BarChart3, Shield } from 'lucide-react';
import { useAuth } from '@/app/context/AuthContext';
import Link from 'next/link';

const SSE_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface DataHealth {
    tenant_id: string;
    entities: number;
    relationships: number;
    alarms: number;
    alarm_by_severity: Record<string, number>;
    customers: number;
    neighbour_relations: number;
    kpi: {
        entities_with_kpi: number;
        total_samples: number;
        time_range: { earliest: string; latest: string } | null;
    };
    incidents: {
        total: number;
        open: number;
    };
    last_reconciliation: {
        run_id: string;
        status: string;
        total_divergences: number;
        dark_nodes: number;
        phantom_nodes: number;
        dark_edges: number;
        phantom_edges: number;
        completed_at: string | null;
    } | null;
}

interface DataHealthPanelProps {
    onIngestionComplete?: () => void;
}

function MetricCard({ label, value, sublabel, icon, href }: {
    label: string;
    value: string | number;
    sublabel?: string;
    icon: React.ReactNode;
    href?: string;
}) {
    const content = (
        <div className="bg-[#06203b] rounded-lg p-4 border border-cyan-900/30 hover:border-cyan-700/40 transition-colors">
            <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-white/60 uppercase tracking-wider">{label}</span>
                <span className="text-white/40">{icon}</span>
            </div>
            <p className="text-2xl font-bold text-white">{typeof value === 'number' ? value.toLocaleString() : value}</p>
            {sublabel && <p className="text-xs text-white/60 mt-1">{sublabel}</p>}
        </div>
    );
    if (href) return <Link href={href} className="block">{content}</Link>;
    return content;
}

export default function DataHealthPanel({ onIngestionComplete }: DataHealthPanelProps) {
    const { token, role, authFetch, getToken } = useAuth();
    const [health, setHealth] = useState<DataHealth | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Ingestion state (admin only)
    const [ingestionRunning, setIngestionRunning] = useState(false);
    const [ingestionProgress, setIngestionProgress] = useState(0);
    const [ingestionLogs, setIngestionLogs] = useState<string[]>([]);

    const isAdmin = role === 'admin' || role === 'tenant_admin';

    const fetchHealth = async () => {
        if (!token) return;
        try {
            setLoading(true);
            const res = await authFetch("/api/v1/reports/data-health");
            if (res.ok) {
                setHealth(await res.json());
                setError(null);
            } else {
                setError(`Failed to load data health (HTTP ${res.status})`);
            }
        } catch (err: any) {
            setError(err.message || 'Failed to load data health');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchHealth();
    }, [token]);

    const handleStartIngestion = async () => {
        if (!token) return;
        try {
            setIngestionLogs(["--- Starting Ingestion ---"]);
            setIngestionProgress(0);
            const res = await authFetch("/api/v1/ingestion/start", {
                method: 'POST',
                body: JSON.stringify({ dry_run: false }),
            });
            if (res.ok) {
                setIngestionRunning(true);
                // Start SSE
                const es = new EventSource(`${SSE_BASE_URL}/api/v1/ingestion/stream?token=${encodeURIComponent(getToken())}`);
                es.onmessage = (ev) => {
                    try {
                        const data = JSON.parse(ev.data);
                        if (data.event === 'ingestion_log') {
                            setIngestionLogs(prev => [...prev, data.data.line]);
                            setIngestionProgress(data.data.progress);
                        } else if (data.event === 'ingestion_completed') {
                            setIngestionRunning(false);
                            setIngestionProgress(100);
                            setIngestionLogs(prev => [...prev, "--- Ingestion Completed ---"]);
                            es.close();
                            // Refresh data health
                            fetchHealth();
                            if (onIngestionComplete) onIngestionComplete();
                        } else if (data.event === 'ingestion_error') {
                            setIngestionRunning(false);
                            setIngestionLogs(prev => [...prev, `ERROR: ${data.data.error}`]);
                            es.close();
                        }
                    } catch (e) {
                        console.warn("SSE parse error", e);
                    }
                };
                es.onerror = () => { es.close(); };
            } else {
                const err = await res.json();
                setIngestionLogs(prev => [...prev, `Failed to start: ${err.detail || 'Unknown error'}`]);
            }
        } catch (e: any) {
            setIngestionLogs(prev => [...prev, `Exception: ${e.message}`]);
        }
    };

    const hasData = health && health.entities > 0;
    const recon = health?.last_reconciliation;

    return (
        <div className="bg-[#0a2d4a] rounded-xl p-6 border border-[rgba(7,242,219,0.12)] mt-6 shadow-[0_2px_8px_rgba(0,0,0,0.15)]">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center">
                        <Database className="w-5 h-5 mr-2 text-cyan-400" />
                        Tenant Data Health
                    </h2>
                    <p className="text-sm text-white/80 mt-1">
                        Operational data inventory and intelligence readiness
                    </p>
                </div>
                <div className="flex space-x-3 mt-4 md:mt-0">
                    {recon && (
                        <Link
                            href="/divergence"
                            className="flex items-center justify-center px-4 py-2 rounded-md font-medium bg-violet-500 text-white hover:bg-violet-400 transition-colors text-sm"
                        >
                            <GitCompare className="w-4 h-4 mr-2" />
                            Divergence Analysis
                        </Link>
                    )}
                    {isAdmin && (
                        <button
                            onClick={handleStartIngestion}
                            disabled={ingestionRunning}
                            className={`flex items-center justify-center px-4 py-2 rounded-md font-medium transition-colors text-sm ${ingestionRunning
                                    ? 'bg-white/10 text-white/40 cursor-not-allowed'
                                    : 'bg-cyan-400 text-gray-950 font-bold hover:bg-cyan-300'
                                }`}
                        >
                            {ingestionRunning ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
                            {ingestionRunning ? 'Ingesting...' : 'Start Ingestion'}
                        </button>
                    )}
                </div>
            </div>

            {loading ? (
                <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-6 h-6 text-cyan-400 animate-spin" />
                    <span className="ml-3 text-white/60 text-sm">Loading data health...</span>
                </div>
            ) : error ? (
                <div className="text-center py-6">
                    <p className="text-white/80 font-medium">Unable to load data health</p>
                    <p className="text-white/60 text-sm mt-1">{error}</p>
                </div>
            ) : !hasData ? (
                <div className="text-center py-8">
                    <Database className="w-10 h-10 text-white/30 mx-auto mb-3" />
                    <p className="text-white/80 text-lg font-medium mb-2">No Data Ingested</p>
                    <p className="text-white/60 text-sm max-w-md mx-auto">
                        This tenant has no operational data. Use the Start Ingestion button to load
                        CMDB entities, alarms, KPI telemetry, and customer data from parquet files.
                    </p>
                </div>
            ) : (
                <>
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        <MetricCard
                            label="CMDB Entities"
                            value={health!.entities}
                            sublabel={`${health!.relationships.toLocaleString()} relationships`}
                            icon={<Network className="w-4 h-4" />}
                            href="/topology"
                        />
                        <MetricCard
                            label="Alarms"
                            value={health!.alarms}
                            sublabel={Object.entries(health!.alarm_by_severity).slice(0, 3).map(([s, c]) => `${s}: ${c}`).join(', ') || 'No alarms'}
                            icon={<AlertTriangle className="w-4 h-4" />}
                        />
                        <MetricCard
                            label="Customers"
                            value={health!.customers}
                            icon={<Users className="w-4 h-4" />}
                        />
                        <MetricCard
                            label="KPI Coverage"
                            value={health!.kpi.entities_with_kpi}
                            sublabel={health!.kpi.total_samples > 0
                                ? `${(health!.kpi.total_samples / 1000000).toFixed(1)}M samples`
                                : 'No KPI data loaded'}
                            icon={<Activity className="w-4 h-4" />}
                        />
                        <MetricCard
                            label="Incidents"
                            value={health!.incidents.total}
                            sublabel={health!.incidents.open > 0 ? `${health!.incidents.open} open` : 'None open'}
                            icon={<Shield className="w-4 h-4" />}
                            href="/incidents"
                        />
                        <MetricCard
                            label="Neighbour Relations"
                            value={health!.neighbour_relations}
                            icon={<GitCompare className="w-4 h-4" />}
                        />
                        {health!.kpi.time_range && (
                            <MetricCard
                                label="Data Window"
                                value={new Date(health!.kpi.time_range.earliest).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })
                                    + ' - ' + new Date(health!.kpi.time_range.latest).toLocaleDateString('en-GB', { month: 'short', day: 'numeric', year: 'numeric' })}
                                icon={<BarChart3 className="w-4 h-4" />}
                            />
                        )}
                        {recon && (
                            <MetricCard
                                label="Divergences"
                                value={recon.total_divergences}
                                sublabel={`Dark: ${recon.dark_nodes} | Phantom: ${recon.phantom_nodes} | Edges: ${recon.dark_edges}`}
                                icon={<GitCompare className="w-4 h-4" />}
                                href="/divergence"
                            />
                        )}
                    </div>
                </>
            )}

            {/* Ingestion Progress (only when running) */}
            {(ingestionRunning || ingestionLogs.length > 0) && (
                <div className="mt-4 space-y-3">
                    <div className="flex justify-between text-xs text-white/50 mb-1">
                        <span>Ingestion Progress</span>
                        <span>{ingestionProgress}%</span>
                    </div>
                    <div className="w-full bg-[#06203b] rounded-full h-2">
                        <div
                            className="bg-cyan-400 h-2 rounded-full transition-all duration-500 ease-out"
                            style={{ width: `${ingestionProgress}%` }}
                        />
                    </div>
                    <div className="bg-black/50 rounded border border-cyan-900/30 p-3 h-36 overflow-y-auto font-mono text-xs text-green-400">
                        {ingestionLogs.map((log, i) => (
                            <div key={i} className="mb-1 leading-relaxed opacity-90">{log}</div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
