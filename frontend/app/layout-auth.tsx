"use client";

import React, { useState, useEffect } from "react";
import Navigation from "./components/Navigation";
import { AuthProvider } from "./context/AuthContext";

// ── Session persistence helpers ─────────────────────────────────
const SESSION_KEYS = {
  token: "pedkai_token",
  tenantId: "pedkai_tenant_id",
  tenantName: "pedkai_tenant_name",
  role: "pedkai_role",
} as const;

function persistSession(tok: string, tid: string, tname: string, r: string) {
  try {
    sessionStorage.setItem(SESSION_KEYS.token, tok);
    sessionStorage.setItem(SESSION_KEYS.tenantId, tid);
    sessionStorage.setItem(SESSION_KEYS.tenantName, tname);
    sessionStorage.setItem(SESSION_KEYS.role, r);
  } catch {
    // sessionStorage unavailable (SSR, private browsing edge cases)
  }
}

function clearSession() {
  try {
    Object.values(SESSION_KEYS).forEach((k) => sessionStorage.removeItem(k));
  } catch {}
}

function loadSession(): { token: string; tenantId: string; tenantName: string; role: string } | null {
  try {
    const token = sessionStorage.getItem(SESSION_KEYS.token);
    const tenantId = sessionStorage.getItem(SESSION_KEYS.tenantId);
    const tenantName = sessionStorage.getItem(SESSION_KEYS.tenantName);
    if (token && tenantId && tenantName) {
      // role may be absent in sessions created before this feature was deployed;
      // fall back to "" so the user stays logged in without data loss.
      // The admin nav link simply won't appear until they re-login.
      const role = sessionStorage.getItem(SESSION_KEYS.role) ?? "";
      return { token, tenantId, tenantName, role };
    }
  } catch {}
  return null;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface TenantInfo {
  id: string;
  display_name: string;
}

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // ── Auth state ──────────────────────────────────────────────────
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("operator");
  const [authError, setAuthError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showPasswordWarning, setShowPasswordWarning] = useState(false);

  // ── Tenant selection state ──────────────────────────────────────
  const [tenants, setTenants] = useState<TenantInfo[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null);
  const [tenantName, setTenantName] = useState<string>("");
  const [role, setRole] = useState<string>("");
  const [tenantBound, setTenantBound] = useState(false);
  const [tenantError, setTenantError] = useState("");
  const [isTenantLoading, setIsTenantLoading] = useState(false);

  // ── Rehydrate from sessionStorage on mount ─────────────────────
  useEffect(() => {
    const saved = loadSession();
    if (saved) {
      setToken(saved.token);
      setSelectedTenantId(saved.tenantId);
      setTenantName(saved.tenantName);
      setRole(saved.role);
      setTenantBound(true);
    }
  }, []);

  // ── Phase: 'login' | 'tenant-select' | 'app' ───────────────────
  // Derived from state rather than stored separately to avoid drift.
  const phase = !token ? "login" : !tenantBound ? "tenant-select" : "app";

  // ── Logout (full reset) ─────────────────────────────────────────
  const handleLogout = () => {
    clearSession();
    setToken(null);
    setTenants([]);
    setSelectedTenantId(null);
    setTenantName("");
    setRole("");
    setTenantBound(false);
    setTenantError("");
    setUsername("operator");
    setPassword("operator");
    setAuthError("");
    setShowPasswordWarning(false);
  };

  // ── Login handler ───────────────────────────────────────────────
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError("");
    setIsLoading(true);

    try {
      const formData = new URLSearchParams();
      formData.append("username", username);
      formData.append("password", password);

      const res = await fetch(`${API_BASE_URL}/api/v1/auth/token`, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: formData,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? "Invalid credentials");
      }

      const data = await res.json();

      if (username === "operator") setShowPasswordWarning(true);

      // The /token response now includes a tenants[] array.
      const returnedTenants: TenantInfo[] = data.tenants ?? [];

      if (returnedTenants.length === 0) {
        // Case C: No tenant mapping → deny access
        setAuthError(
          "No authorized tenants for this account. Contact your administrator.",
        );
        return;
      }

      if (returnedTenants.length === 1) {
        // Case A: Single tenant → auto-bind (token already has tenant_id)
        setToken(data.access_token);
        setTenants(returnedTenants);
        setSelectedTenantId(returnedTenants[0].id);
        setTenantName(returnedTenants[0].display_name);
        setRole(data.role ?? "");
        setTenantBound(true);
        persistSession(data.access_token, returnedTenants[0].id, returnedTenants[0].display_name, data.role ?? "");
        return;
      }

      // Case B: Multiple tenants → store preliminary token, show picker
      setToken(data.access_token);
      setTenants(returnedTenants);
      setSelectedTenantId(returnedTenants[0].id); // pre-select first
    } catch (err: any) {
      setAuthError(err.message ?? "Login failed. Check backend credentials.");
    } finally {
      setIsLoading(false);
    }
  };

  // ── Tenant selection handler ────────────────────────────────────
  const handleSelectTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTenantId || !token) return;

    setTenantError("");
    setIsTenantLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/select-tenant`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ tenant_id: selectedTenantId }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }

      const data = await res.json();

      // Replace the preliminary token with the tenant-scoped one
      setToken(data.access_token);
      setSelectedTenantId(data.tenant_id);
      setTenantName(data.tenant_name);
      setRole(data.role ?? "");
      setTenantBound(true);
      persistSession(data.access_token, data.tenant_id, data.tenant_name, data.role ?? "");
    } catch (err: any) {
      setTenantError(err.message ?? "Failed to select tenant.");
    } finally {
      setIsTenantLoading(false);
    }
  };

  // ═══════════════════════════════════════════════════════════════
  // RENDER: Login screen
  // ═══════════════════════════════════════════════════════════════
  if (phase === "login") {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-[#06203b] via-[#030f26] to-[#06203b]">
        <div className="w-full max-w-md animate-fade-in">
          <div className="bg-[#0a2d4a] rounded-2xl border border-[rgba(7,242,219,0.12)] p-8 shadow-[0_16px_48px_rgba(0,0,0,0.35)]">
            <div className="flex flex-col items-center mb-8">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo.jpeg" alt="pedk.ai" className="w-20 h-20 rounded-2xl mb-4 shadow-[0_0_20px_rgba(7,242,219,0.15)]" />
              <h1 className="text-2xl font-bold text-white tracking-tight">pedk.ai</h1>
              <p className="text-sm text-white/60 mt-1">NOC Command Center</p>
            </div>

            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-white mb-2">
                  Username
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg bg-[#06203b] border border-[rgba(7,242,219,0.15)] text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-cyan-400/50 focus:border-cyan-400/30 transition-colors duration-200"
                  placeholder="operator"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-white mb-2">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg bg-[#06203b] border border-[rgba(7,242,219,0.15)] text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-cyan-400/50 focus:border-cyan-400/30 transition-colors duration-200"
                  placeholder="••••••"
                />
              </div>

              {authError && (
                <div className="p-3 rounded-lg bg-red-900 border border-red-700 text-red-200 text-sm">
                  {authError}
                </div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg bg-cyan-400 hover:bg-cyan-300 disabled:opacity-50 disabled:cursor-not-allowed text-gray-950 font-bold transition-all duration-200 hover:shadow-[0_0_16px_rgba(7,242,219,0.25)]"
              >
                {isLoading ? "Logging in..." : "Login"}
              </button>
            </form>

            {showPasswordWarning && (
              <div className="mt-4 p-3 rounded-lg bg-yellow-900 border border-yellow-700 text-yellow-200 text-sm">
                ⚠️ Default credentials in use. Change password in production.
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════
  // RENDER: Tenant selection screen
  // ═══════════════════════════════════════════════════════════════
  if (phase === "tenant-select") {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-[#06203b] via-[#030f26] to-[#06203b]">
        <div className="w-full max-w-md animate-fade-in">
          <div className="bg-[#0a2d4a] rounded-2xl border border-[rgba(7,242,219,0.12)] p-8 shadow-[0_16px_48px_rgba(0,0,0,0.35)]">
            <div className="flex flex-col items-center mb-6">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo.jpeg" alt="pedk.ai" className="w-16 h-16 rounded-xl mb-3 shadow-[0_0_16px_rgba(7,242,219,0.1)]" />
              <h1 className="text-2xl font-bold text-white tracking-tight">pedk.ai</h1>
              <p className="text-white/60 text-sm mt-1">
                Select a tenant to continue
              </p>
            </div>

            <form onSubmit={handleSelectTenant} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-white mb-2">
                  Tenant
                </label>
                <select
                  value={selectedTenantId ?? ""}
                  onChange={(e) => setSelectedTenantId(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-lg bg-[#06203b] border border-[rgba(7,242,219,0.15)] text-white focus:outline-none focus:ring-2 focus:ring-cyan-400/50 focus:border-cyan-400/30 transition-colors duration-200"
                >
                  {tenants.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.display_name}
                    </option>
                  ))}
                </select>
              </div>

              <p className="text-xs text-white/80">
                You have access to {tenants.length} tenant
                {tenants.length > 1 ? "s" : ""}. To switch tenants later you
                must log out and log back in.
              </p>

              {tenantError && (
                <div className="p-3 rounded-lg bg-red-900 border border-red-700 text-red-200 text-sm">
                  {tenantError}
                </div>
              )}

              <button
                type="submit"
                disabled={isTenantLoading || !selectedTenantId}
                className="w-full px-4 py-2.5 rounded-lg bg-cyan-400 hover:bg-cyan-300 disabled:opacity-50 disabled:cursor-not-allowed text-gray-950 font-bold transition-all duration-200 hover:shadow-[0_0_16px_rgba(7,242,219,0.25)]"
              >
                {isTenantLoading ? "Selecting..." : "Continue"}
              </button>

              <button
                type="button"
                onClick={handleLogout}
                className="w-full px-4 py-2 rounded-lg border border-cyan-900/50 text-slate-400 hover:text-white hover:border-cyan-700/50 text-sm transition-colors"
              >
                Back to login
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════
  // RENDER: Authenticated app (tenant bound)
  // ═══════════════════════════════════════════════════════════════
  return (
    <AuthProvider
      token={token!}
      tenantId={selectedTenantId!}
      tenantName={tenantName}
      role={role}
      onLogout={handleLogout}
    >
      <Navigation />
      <main className="w-full px-4 md:px-8 animate-fade-in">{children}</main>
    </AuthProvider>
  );
}
