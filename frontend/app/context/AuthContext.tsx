"use client";

import React, { createContext, useContext } from "react";

interface AuthContextType {
  token: string;
  tenantId: string;
  tenantName: string;
  role: string;
  onLogout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  token: "",
  tenantId: "",
  tenantName: "",
  role: "",
  onLogout: () => {},
});

export function AuthProvider({
  token,
  tenantId,
  tenantName,
  role,
  onLogout,
  children,
}: {
  token: string;
  tenantId: string;
  tenantName: string;
  role: string;
  onLogout: () => void;
  children: React.ReactNode;
}) {
  return (
    <AuthContext.Provider value={{ token, tenantId, tenantName, role, onLogout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
