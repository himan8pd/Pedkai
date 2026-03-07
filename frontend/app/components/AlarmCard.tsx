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
                    ? "bg-slate-900 border-slate-900 ring-1 ring-blue-600"
                    : "bg-slate-900 border-slate-800 hover:border-slate-900 hover:bg-slate-800"
            )}
        >
            <div className="flex justify-between items-start mb-2">
                <div className="flex items-center gap-2">
                    <div className={cn(
                        "w-2.5 h-2.5 rounded-full relative",
                        isCritical ? "bg-rose-500 pulse" : "bg-blue-600"
                    )} />
                    <span className="text-[11px] font-black text-white uppercase tracking-tighter truncate max-w-[80px]">{alarm.id}</span>
                </div>
                <span className="text-[10px] text-white font-medium">{new Date(alarm.eventTime).toLocaleTimeString()}</span>
            </div>
            <h4 className="font-bold text-white group-hover:text-blue-600 transition-colors uppercase text-sm tracking-tight truncate">{alarm.specificProblem}</h4>
            <p className="text-xs text-white mt-1 flex items-center gap-1">
                <Network className="w-3 h-3 text-white" /> {alarm.alarmedObject?.id || "Unknown Entity"}
            </p>
        </div>
    )
}
