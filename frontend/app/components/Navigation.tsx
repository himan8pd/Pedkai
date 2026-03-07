"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import {
  LayoutDashboard,
  AlertTriangle,
  BarChart3,
  Network,
  LogOut,
  Building2,
  Clock,
  GitCompare,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { usePathname } from "next/navigation";
import { useAuth } from "@/app/context/AuthContext";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Navigation() {
  const pathname = usePathname();
  const { onLogout, tenantName, tenantId } = useAuth();
  const [dataMode, setDataMode] = useState<string | null>(null);
  const [dataPeriod, setDataPeriod] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantId) return;

    async function fetchDataStatus() {
      try {
        const res = await fetch(
          `${API_BASE_URL}/api/v1/data-status?tenant_id=${encodeURIComponent(tenantId)}`,
        );
        if (res.ok) {
          const data = await res.json();
          setDataMode(data.mode ?? null);
          if (data.data_period?.earliest && data.data_period?.latest) {
            const earliest = new Date(data.data_period.earliest);
            const latest = new Date(data.data_period.latest);
            const fmtOpts: Intl.DateTimeFormatOptions = {
              year: "numeric",
              month: "short",
              day: "numeric",
            };
            const e = earliest.toLocaleDateString("en-GB", fmtOpts);
            const l = latest.toLocaleDateString("en-GB", fmtOpts);
            setDataPeriod(`${e} – ${l}`);
          }
        }
      } catch {
        // Silently ignore — banner simply won't show
      }
    }

    fetchDataStatus();
  }, [tenantId]);

  const navItems = [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/incidents", label: "Incidents", icon: AlertTriangle },
    { href: "/scorecard", label: "Scorecard", icon: BarChart3 },
    { href: "/divergence", label: "Divergence", icon: GitCompare },
    { href: "/topology", label: "Topology", icon: Network },
  ];

  return (
    <nav className="bg-[#06203b] border-b border-cyan-900/40 sticky top-0 z-50">
      <div className="w-full px-4 md:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo — clickable link to dashboard */}
          <Link
            href="/dashboard"
            className="flex items-center space-x-2.5 hover:opacity-80 transition-opacity"
          >
            <Image src="/logo.jpeg" alt="pedk.ai" width={32} height={32} className="rounded-lg" />
            <span className="text-lg font-bold text-white tracking-tight">pedk.ai</span>
          </Link>

          {/* Navigation Links */}
          <div className="flex items-center space-x-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center space-x-2",
                    isActive
                      ? "bg-cyan-500/10 text-white border border-cyan-400/60"
                      : "text-white border border-white/25 hover:border-white/60 hover:bg-white/10",
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span className="hidden sm:inline">{item.label}</span>
                </Link>
              );
            })}
          </div>

          {/* Tenant badge + Historic banner + Logout */}
          <div className="flex items-center space-x-3">
            {tenantName && (
              <div className="hidden md:flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-[#0a2d4a] border border-cyan-900/40 text-xs text-white">
                <Building2 className="w-3.5 h-3.5 text-cyan-400" />
                <span className="font-medium">{tenantName}</span>
              </div>
            )}
            {dataMode === "historic" && (
              <div className="hidden md:flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-amber-900/50 border border-amber-600/50 text-xs text-amber-300">
                <Clock className="w-3.5 h-3.5" />
                <span>
                  Historic Analysis{dataPeriod ? ` — ${dataPeriod}` : ""}
                </span>
              </div>
            )}
            <button
              onClick={onLogout}
              className="px-3 py-2 rounded-lg text-sm font-medium text-slate-200 hover:text-red-400 hover:bg-white/5 transition-colors flex items-center space-x-2"
            >
              <LogOut className="w-4 h-4" />
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
