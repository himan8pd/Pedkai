"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import {
  AlertTriangle,
  BarChart3,
  Network,
  LogOut,
  Building2,
  Clock,
  GitCompare,
  Radio,
  MessageSquare,
  Settings,
  Users,
  Sun,
  Moon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { usePathname } from "next/navigation";
import { useAuth } from "@/app/context/AuthContext";
import { useTheme } from "@/app/context/ThemeContext";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Navigation() {
  const pathname = usePathname();
  const { onLogout, tenantName, tenantId, role } = useAuth();
  const { theme, toggleTheme } = useTheme();
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
    { href: "/incidents", label: "Incidents", icon: AlertTriangle },
    { href: "/scorecard", label: "Scorecard", icon: BarChart3 },
    { href: "/divergence", label: "Divergence", icon: GitCompare },
    { href: "/topology", label: "Topology", icon: Network },
    { href: "/sleeping-cells", label: "Sleeping Cells", icon: Radio },
    { href: "/feedback", label: "Feedback", icon: MessageSquare },
    { href: "/settings", label: "Settings", icon: Settings },
    ...(role === "admin" || role === "tenant_admin"
      ? [{ href: "/admin", label: "Admin", icon: Users }]
      : []),
  ];

  return (
    <nav className="bg-[#06203b]/95 backdrop-blur-md border-b border-[rgba(7,242,219,0.12)] sticky top-0 z-50 shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="w-full pr-4 md:pr-8">
        <div className="flex items-center justify-between h-[52px] md:h-[70px] lg:h-[86px]">
          {/* Logo — clickable home link to dashboard, flush top-left */}
          <Link
            href="/dashboard"
            className="flex-shrink-0 flex items-center hover:opacity-80 transition-opacity self-start"
          >
            <Image
              src="/logo-v2.jpeg"
              alt="pedk.ai"
              width={86}
              height={86}
              className="object-cover min-w-[52px] min-h-[52px] w-[52px] h-[52px] md:w-[70px] md:h-[70px] lg:w-[86px] lg:h-[86px]"
              unoptimized
            />
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
                    "px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 flex items-center space-x-1.5",
                    isActive
                      ? "bg-cyan-400/15 text-cyan-300 border border-cyan-400/40 shadow-[0_0_8px_rgba(7,242,219,0.1)]"
                      : "text-white/70 hover:text-white hover:bg-white/5 border border-transparent hover:border-white/10",
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
              <div className="hidden md:flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-white/10 border border-white/15 text-xs text-white/80">
                <Building2 className="w-3.5 h-3.5 text-cyan-400/70" />
                <span className="font-medium">{tenantName}</span>
              </div>
            )}
            {dataMode === "historic" && (
              <div className="hidden md:flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-amber-500/10 border border-amber-500/25 text-xs text-amber-300">
                <Clock className="w-3.5 h-3.5" />
                <span>
                  Historic Analysis{dataPeriod ? ` — ${dataPeriod}` : ""}
                </span>
              </div>
            )}
            <button
              onClick={toggleTheme}
              className="p-1.5 rounded-lg text-white/60 hover:text-cyan-300 hover:bg-white/5 transition-all duration-200 border border-transparent hover:border-white/10"
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            >
              {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
            <button
              onClick={onLogout}
              className="px-3 py-1.5 rounded-lg text-sm font-medium text-white/60 hover:text-red-400 hover:bg-red-500/10 transition-all duration-200 flex items-center space-x-1.5 border border-transparent hover:border-red-500/20"
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
