"use client";

import React, { createContext, useContext, useEffect, useRef, useCallback } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

/** How often to silently refresh the token (in ms). Default: 20 minutes. */
const REFRESH_INTERVAL_MS = 20 * 60 * 1000;

interface AuthContextType {
  token: string;
  tenantId: string;
  tenantName: string;
  role: string;
  onLogout: () => void;
  /** Wrapper around fetch that auto-injects auth headers and handles 401. */
  authFetch: (path: string, opts?: RequestInit) => Promise<Response>;
  /** Returns the current (possibly refreshed) token — use for SSE query params. */
  getToken: () => string;
}

const AuthContext = createContext<AuthContextType>({
  token: "",
  tenantId: "",
  tenantName: "",
  role: "",
  onLogout: () => {},
  authFetch: () => Promise.reject(new Error("AuthContext not initialized")),
  getToken: () => "",
});

export function AuthProvider({
  token,
  tenantId,
  tenantName,
  role,
  onLogout,
  onTokenRefresh,
  children,
}: {
  token: string;
  tenantId: string;
  tenantName: string;
  role: string;
  onLogout: () => void;
  onTokenRefresh: (newToken: string) => void;
  children: React.ReactNode;
}) {
  const tokenRef = useRef(token);
  tokenRef.current = token;

  const getToken = useCallback(() => tokenRef.current, []);

  // ── Silent token refresh ──────────────────────────────────────
  useEffect(() => {
    if (!token) return;

    const refresh = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${tokenRef.current}`,
          },
        });
        if (res.ok) {
          const data = await res.json();
          onTokenRefresh(data.access_token);
        } else if (res.status === 401) {
          // Token already expired and cannot be refreshed — force re-login
          onLogout();
        }
      } catch {
        // Network error — don't logout, will retry next interval
      }
    };

    const id = setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [token, onLogout, onTokenRefresh]);

  // ── authFetch: centralized fetch with 401 handling ────────────
  const authFetch = useCallback(
    async (path: string, opts?: RequestInit): Promise<Response> => {
      const res = await fetch(`${API_BASE_URL}${path}`, {
        ...opts,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${tokenRef.current}`,
          ...(opts?.headers ?? {}),
        },
      });

      if (res.status === 401) {
        onLogout();
        throw new Error("Session expired. Please log in again.");
      }

      return res;
    },
    [onLogout],
  );

  return (
    <AuthContext.Provider value={{ token, tenantId, tenantName, role, onLogout, authFetch, getToken }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
