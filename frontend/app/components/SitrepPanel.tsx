import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Activity, CheckCircle, Network } from 'lucide-react'
import { cn } from '@/lib/utils'

interface SitrepPanelProps {
    selectedAlarm: any
    onAcknowledge: (id: string) => void
}

export default function SitrepPanel({ selectedAlarm, onAcknowledge }: SitrepPanelProps) {
    return (
        <section className="flex-1 glass rounded-2xl border-slate-800 flex flex-col relative overflow-hidden">
            <AnimatePresence mode="wait">
                {selectedAlarm ? (
                    <motion.div
                        key={selectedAlarm.id}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                        className="p-8 flex flex-col h-full"
                    >
                        <div className="flex justify-between items-start mb-8">
                            <div>
                                <div className="flex items-center gap-2 mb-1">
                                    <span className={cn(
                                        "uppercase text-[10px] font-black px-2 py-0.5 rounded tracking-widest",
                                        selectedAlarm.perceivedSeverity === 'critical'
                                            ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                                            : 'bg-orange-500/20 text-orange-400 border border-orange-500/40'
                                    )}>
                                        {selectedAlarm.perceivedSeverity}
                                    </span>
                                    <span className="text-slate-500 text-xs">{selectedAlarm.id}</span>
                                    {selectedAlarm.ackState === 'acknowledged' && (
                                        <CheckCircle className="w-3 h-3 text-emerald-500" />
                                    )}
                                </div>
                                <h2 className="text-3xl font-bold text-white uppercase">{selectedAlarm.specificProblem}</h2>
                                <p className="text-slate-400 mt-1 flex items-center gap-1.5">
                                    <Network className="w-4 h-4" /> {selectedAlarm.alarmedObject?.id || selectedAlarm.entity}
                                </p>
                            </div>
                            {selectedAlarm.ackState !== 'acknowledged' && (
                                <button
                                    onClick={() => onAcknowledge(selectedAlarm.id)}
                                    className="px-6 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg font-bold transition-all glow active:scale-95 shadow-lg shadow-cyan-900/20"
                                >
                                    Acknowledge Alarm
                                </button>
                            )}
                        </div>

                        <div className="grid grid-cols-2 gap-8 flex-1 content-start">
                            <div className="space-y-6">
                                <h3 className="text-cyan-400 text-xs font-black uppercase tracking-widest">Autonomous SITREP</h3>
                                {/* AI-Generated watermark — Task 3.3 / Legal Counsel §2.14 mandate */}
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                                    🤖 AI Generated — Advisory Only
                                </span>
                                <div className="prose prose-invert max-w-none text-slate-300 bg-slate-900/50 p-6 rounded-xl border border-slate-800/50 leading-relaxed shadow-inner">
                                    <p className="font-bold text-white mb-2">### EXECUTIVE SUMMARY</p>
                                    <p>Critical anomaly detected on {selectedAlarm.alarmedObject?.id}. AI Analysis pending.</p>
                                </div>
                            </div>
                        </div>
                    </motion.div>
                ) : (
                    <div className="flex-1 flex flex-col items-center justify-center text-slate-500 opacity-50">
                        <Activity className="w-24 h-24 mb-4" />
                        <p className="text-lg tracking-widest uppercase font-black">Select an incident to analyze</p>
                    </div>
                )}
            </AnimatePresence>
        </section>
    )
}
