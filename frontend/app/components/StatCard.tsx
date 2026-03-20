import React from 'react'

interface StatCardProps {
    icon: React.ReactNode
    label: string
    value: string
}

export default function StatCard({ icon, label, value }: StatCardProps) {
    return (
        <div className="flex items-center gap-3 bg-[#0a2d4a] px-4 py-3 rounded-xl border border-[rgba(7,242,219,0.12)] shadow-[0_2px_8px_rgba(0,0,0,0.2)] transition-all duration-200 hover:border-[rgba(7,242,219,0.25)] hover:shadow-[0_4px_16px_rgba(0,0,0,0.25)]">
            <div className="p-2 bg-cyan-400/10 rounded-lg text-cyan-400">{icon}</div>
            <div>
                <p className="text-[10px] uppercase font-bold text-white/55 leading-tight tracking-wider">{label}</p>
                <p className="text-lg font-black leading-tight text-white">{value}</p>
            </div>
        </div>
    )
}
