"use client"

import React, { createContext, useContext } from 'react'

interface AuthContextType {
  token: string
  onLogout: () => void
}

const AuthContext = createContext<AuthContextType>({
  token: '',
  onLogout: () => {},
})

export function AuthProvider({
  token,
  onLogout,
  children,
}: {
  token: string
  onLogout: () => void
  children: React.ReactNode
}) {
  return (
    <AuthContext.Provider value={{ token, onLogout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
