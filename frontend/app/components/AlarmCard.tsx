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
                "p-4 rounded-xl cursor-pointer transition-all duration-200 relative overflow-hidden group border",
                isSelected
                    ? "bg-[#0d3b5e] border-cyan-400/40 ring-1 ring-cyan-400/30 shadow-[0_0_12px_rgba(7,242,219,0.08)]"
                    : "bg-[#0a2d4a] border-[rgba(7,242,219,0.1)] hover:border-[rgba(7,242,219,0.2)] hover:bg-[#0d3b5e]/70"
            )}
        >
            <div className="flex justify-between items-start mb-2">
                <div className="flex items-center gap-2">
                    <div className={cn(
                        "w-2.5 h-2.5 rounded-full relative",
                        isCritical ? "bg-rose-500 pulse" : "bg-cyan-400"
                    )} />
                    <span className="text-[11px] font-black text-white/60 uppercase tracking-tighter truncate max-w-[80px]">{alarm.id}</span>
                </div>
                <span className="text-[10px] text-white/50 font-medium">{new Date(alarm.eventTime).toLocaleTimeString()}</span>
            </div>
            <h4 className="font-bold text-white group-hover:text-cyan-300 transition-colors uppercase text-sm tracking-tight truncate">{alarm.specificProblem}</h4>
            <p className="text-xs text-white/60 mt-1 flex items-center gap-1">
                <Network className="w-3 h-3 text-white/40" /> {alarm.alarmedObject?.id || "Unknown Entity"}
            </p>
        </div>
    )
}
