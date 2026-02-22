import React from 'react'
import { Network } from 'lucide-react'
import { cn } from '@/lib/utils'

interface AlarmCardProps {
    alarm: any
    isSelected: boolean
    onClick: () => void
}

export default function AlarmCard({ alarm, isSelected, onClick }: AlarmCardProps) {
    // TMF642 Field Mapping
    const isCritical = alarm.perceivedSeverity === 'critical'

    return (
        <div
            onClick={onClick}
            className={cn(
                "p-4 rounded-xl cursor-pointer transition-all duration-300 relative overflow-hidden group border",
                isSelected
                    ? "bg-cyan-500/10 border-cyan-500/50 ring-1 ring-cyan-500/30"
                    : "bg-slate-900/40 border-slate-800 hover:border-slate-700 hover:bg-white/5"
            )}
        >
            <div className="flex justify-between items-start mb-2">
                <div className="flex items-center gap-2">
                    <div className={cn(
                        "w-2.5 h-2.5 rounded-full relative",
                        isCritical ? "bg-rose-500 pulse" : "bg-orange-500"
                    )} />
                    <span className="text-[11px] font-black text-slate-500 uppercase tracking-tighter truncate max-w-[80px]">{alarm.id}</span>
                </div>
                <span className="text-[10px] text-slate-500 font-medium">{new Date(alarm.eventTime).toLocaleTimeString()}</span>
            </div>
            <h4 className="font-bold text-white group-hover:text-cyan-400 transition-colors uppercase text-sm tracking-tight truncate">{alarm.specificProblem}</h4>
            <p className="text-xs text-slate-400 mt-1 flex items-center gap-1">
                <Network className="w-3 h-3" /> {alarm.alarmedObject?.id || "Unknown Entity"}
            </p>
        </div>
    )
}
