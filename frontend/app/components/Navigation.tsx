"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  LayoutDashboard,
  AlertTriangle,
  BarChart3,
  Network,
  LogOut,
  Building2,
  Clock,
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
    { href: "/topology", label: "Topology", icon: Network },
  ];

  return (
    <nav className="bg-gray-900 border-b border-gray-800 sticky top-0 z-50">
      <div className="w-full px-4 md:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo — clickable link to dashboard */}
          <Link
            href="/dashboard"
            className="flex items-center space-x-2 hover:opacity-80 transition-opacity"
          >
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600" />
            <span className="text-lg font-bold text-white">Pedkai</span>
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
                      ? "bg-gray-800 text-white"
                      : "text-gray-400 hover:text-white hover:bg-gray-800",
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
              <div className="hidden md:flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-300">
                <Building2 className="w-3.5 h-3.5 text-blue-400" />
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
              className="px-3 py-2 rounded-lg text-sm font-medium text-gray-400 hover:text-red-400 hover:bg-gray-800 transition-colors flex items-center space-x-2"
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
