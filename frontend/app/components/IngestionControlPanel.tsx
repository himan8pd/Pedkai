"use client";

import React, { useState, useEffect, useRef } from 'react';
import { Play, FileText, CheckCircle, Loader2 } from 'lucide-react';
import { useAuth } from '@/app/context/AuthContext';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface IngestionControlPanelProps {
    onIngestionComplete?: () => void;
}

export default function IngestionControlPanel({ onIngestionComplete }: IngestionControlPanelProps) {
    const { tenantId, token } = useAuth();
    const [running, setRunning] = useState(false);
    const [progress, setProgress] = useState(0);
    const [logs, setLogs] = useState<string[]>([]);
    const [reportStatus, setReportStatus] = useState<'idle' | 'generating' | 'done'>('idle');
    const [reportUrl, setReportUrl] = useState<string | null>(null);

    const esRef = useRef<EventSource | null>(null);
    const logsEndRef = useRef<HTMLDivElement>(null);

    // Auto-scroll logs
    useEffect(() => {
        logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs]);

    useEffect(() => {
        if (!token) return;
        fetch(`${API_BASE_URL}/api/v1/ingestion/status`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(r => r.json())
            .then(data => {
                if (data.running) {
                    setRunning(true);
                    setProgress(data.progress);
                    startSSE();
                }
            })
            .catch(err => console.error("Error fetching ingestion status", err));

        return () => {
            if (esRef.current) {
                esRef.current.close();
            }
        };
    }, [token]);

    const startSSE = () => {
        if (esRef.current) esRef.current.close();

        // Using standard EventSource — token passed as query param (EventSource cannot set headers)
        const es = new EventSource(`${API_BASE_URL}/api/v1/ingestion/stream?token=${encodeURIComponent(token ?? '')}`);
        esRef.current = es;

        es.onmessage = (ev) => {
            try {
                const data = JSON.parse(ev.data);
                if (data.event === 'init') {
                    setRunning(data.data.running);
                    setProgress(data.data.progress);
                } else if (data.event === 'ingestion_log') {
                    setLogs(prev => [...prev, data.data.line]);
                    setProgress(data.data.progress);
                } else if (data.event === 'ingestion_completed') {
                    setRunning(false);
                    setProgress(100);
                    setLogs(prev => [...prev, "--- Ingestion Completed ---"]);
                    es.close();
                    if (onIngestionComplete) onIngestionComplete();
                } else if (data.event === 'ingestion_error') {
                    setRunning(false);
                    setLogs(prev => [...prev, `ERROR: ${data.data.error}`]);
                    es.close();
                }
            } catch (e) {
                console.warn("Error parsing ingestion SSE", e);
            }
        };
        es.onerror = () => {
            // Ignore or close on error
        };
    };

    const handleStartIngestion = async () => {
        if (!token) return;
        try {
            setLogs(["--- Starting Ingestion ---"]);
            setProgress(0);
            const res = await fetch(`${API_BASE_URL}/api/v1/ingestion/start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`
                },
                // Run specific small steps or dry_run if full is too slow for demo
                body: JSON.stringify({ dry_run: false })
            });
            if (res.ok) {
                setRunning(true);
                startSSE();
            } else {
                const err = await res.json();
                setLogs(prev => [...prev, `Failed to start: ${err.detail || 'Unknown error'}`]);
            }
        } catch (e: any) {
            setLogs(prev => [...prev, `Exception: ${e.message}`]);
        }
    };

    const handleGenerateReport = async () => {
        if (!token || !tenantId) return;
        setReportStatus('generating');
        try {
            const res = await fetch(`${API_BASE_URL}/api/v1/reports/divergence/generate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({ tenant_id: tenantId })
            });
            if (res.ok) {
                const data = await res.json();
                setReportStatus('done');
                setReportUrl(data.report_url);
            } else {
                setReportStatus('idle');
            }
        } catch (e) {
            setReportStatus('idle');
        }
    };

    return (
        <div className="bg-[#0a2d4a] rounded-xl p-6 border border-[rgba(7,242,219,0.12)] mt-6 md:col-span-4 lg:col-span-5 shadow-[0_2px_8px_rgba(0,0,0,0.15)]">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center">
                        <Play className="w-5 h-5 mr-2 text-cyan-400" />
                        Ingestion & Reporting Control
                    </h2>
                    <p className="text-sm text-white/80 mt-1">
                        Manage data ingestion and generate Day 1 Divergence Reports.
                    </p>
                </div>
                <div className="flex space-x-3 mt-4 md:mt-0">
                    <button
                        onClick={handleStartIngestion}
                        disabled={running}
                        className={`flex items-center justify-center px-4 py-2 rounded-md font-medium transition-colors ${running
                                ? 'bg-white/10 text-white/40 cursor-not-allowed'
                                : 'bg-cyan-400 text-gray-950 font-bold hover:bg-cyan-300'
                            }`}
                    >
                        {running ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
                        {running ? 'Ingesting...' : 'Start Ingestion'}
                    </button>
                    <button
                        onClick={handleGenerateReport}
                        disabled={reportStatus === 'generating'}
                        className="flex items-center justify-center px-4 py-2 rounded-md font-medium bg-violet-500 text-white hover:bg-violet-400 transition-colors disabled:opacity-50"
                    >
                        {reportStatus === 'generating' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <FileText className="w-4 h-4 mr-2" />}
                        {reportStatus === 'generating' ? 'Generating...' : 'Generate Divergence Report'}
                    </button>
                </div>
            </div>

            {reportStatus === 'done' && reportUrl && (
                <div className="mb-6 p-4 bg-purple-900/30 border border-purple-500/30 rounded-md flex items-start">
                    <CheckCircle className="w-5 h-5 text-purple-400 mt-0.5 mr-3 flex-shrink-0" />
                    <div>
                        <h4 className="text-sm font-medium text-purple-200">Divergence Report Ready</h4>
                        <p className="text-xs text-purple-300/70 mt-1">
                            The Day 1 Divergence Report has been generated. This satisfies the delivery model requirements.
                        </p>
                        <div className="mt-2 text-xs text-purple-400">
                            API Reference: {reportUrl}
                        </div>
                    </div>
                </div>
            )}

            {/* Progress & Logs Section */}
            {(running || logs.length > 0) && (
                <div className="space-y-3">
                    <div className="flex justify-between text-xs text-white/50 mb-1">
                        <span>Progress</span>
                        <span>{progress}%</span>
                    </div>
                    <div className="w-full bg-[#06203b] rounded-full h-2.5">
                        <div
                            className="bg-cyan-400 h-2.5 rounded-full transition-all duration-500 ease-out"
                            style={{ width: `${progress}%` }}
                        ></div>
                    </div>

                    <div className="bg-black/50 rounded border border-cyan-900/30 p-3 h-48 overflow-y-auto font-mono text-xs text-green-400 mt-4">
                        {logs.map((log, i) => (
                            <div key={i} className="mb-1 leading-relaxed opacity-90">{log}</div>
                        ))}
                        <div ref={logsEndRef} />
                    </div>
                </div>
            )}
        </div>
    );
}
