import React from 'react'

interface StatCardProps {
    icon: React.ReactNode
    label: string
    value: string
}

export default function StatCard({ icon, label, value }: StatCardProps) {
    return (
        <div className="flex items-center gap-3 bg-white/5 px-4 py-2 rounded-xl border border-white/10">
            <div className="p-2 bg-slate-900 rounded-lg">{icon}</div>
            <div>
                <p className="text-[10px] uppercase font-bold text-slate-500 leading-tight">{label}</p>
                <p className="text-lg font-black leading-tight">{value}</p>
            </div>
        </div>
    )
}
