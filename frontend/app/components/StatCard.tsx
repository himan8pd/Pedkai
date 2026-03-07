import React from 'react'

interface StatCardProps {
    icon: React.ReactNode
    label: string
    value: string
}

export default function StatCard({ icon, label, value }: StatCardProps) {
    return (
        <div className="flex items-center gap-3 bg-white px-4 py-2 rounded-xl border border-slate-900">
            <div className="p-2 bg-white rounded-lg text-black">{icon}</div>
            <div>
                <p className="text-[10px] uppercase font-bold text-slate-600 leading-tight">{label}</p>
                <p className="text-lg font-black leading-tight text-black">{value}</p>
            </div>
        </div>
    )
}
