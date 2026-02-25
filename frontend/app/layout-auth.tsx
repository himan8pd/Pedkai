"use client"

import React, { useState, useEffect } from 'react'
import Navigation from './components/Navigation'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const [token, setToken] = useState<string | null>(null)
  const [username, setUsername] = useState('operator')
  const [password, setPassword] = useState('operator')
  const [authError, setAuthError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showPasswordWarning, setShowPasswordWarning] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setAuthError('')
    setIsLoading(true)

    try {
      const formData = new URLSearchParams()
      formData.append('username', username)
      formData.append('password', password)

      const res = await fetch(`${API_BASE_URL}/api/v1/auth/token`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
      })

      if (!res.ok) throw new Error('Invalid credentials')

      const data = await res.json()
      setToken(data.access_token)
      if (username === 'operator') setShowPasswordWarning(true)
    } catch (err) {
      setAuthError('Login failed. Check backend credentials.')
    } finally {
      setIsLoading(false)
    }
  }

  if (!token) {
    return (
      <html lang="en">
        <body className="bg-gray-950">
          <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-gray-900 to-black">
            <div className="w-full max-w-md">
              <div className="bg-gray-800 rounded-lg border border-gray-700 p-8 shadow-xl">
                <h1 className="text-2xl font-bold text-white mb-6 text-center">Pedkai</h1>

                <form onSubmit={handleLogin} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Username
                    </label>
                    <input
                      type="text"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="w-full px-4 py-2 rounded-lg bg-gray-700 border border-gray-600 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="operator"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Password
                    </label>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="w-full px-4 py-2 rounded-lg bg-gray-700 border border-gray-600 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
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
                    className="w-full px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 text-white font-semibold transition-colors"
                  >
                    {isLoading ? 'Logging in...' : 'Login'}
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
        </body>
      </html>
    )
  }

  return (
    <html lang="en">
      <body className="bg-gray-950">
        <Navigation />
        <main className="max-w-7xl mx-auto">
          {children}
        </main>
      </body>
    </html>
  )
}
