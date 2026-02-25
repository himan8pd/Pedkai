"use client"

import { redirect } from 'next/navigation'

export default function Home() {
  // Redirect to dashboard
  redirect('/dashboard')
}

  const [alarms, setAlarms] = useState<any[]>([])
  const [selectedAlarm, setSelectedAlarm] = useState<any>(null)
  const [activeView, setActiveView] = useState<'alarms' | 'capacity'>('alarms')
  const [capacityRequests, setCapacityRequests] = useState<any[]>([])
  const [selectedRequest, setSelectedRequest] = useState<any>(null)
  const [investmentPlan, setInvestmentPlan] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [token, setToken] = useState<string | null>(null)
  // Task 5.1: Real scorecard data (replaces hardcoded MTTR/Uptime)
  const [scorecard, setScorecard] = useState<{ avg_mttr: number | null, uptime_pct: number | null } | null>(null)

  // Auth State
  const [username, setUsername] = useState("operator")
  const [password, setPassword] = useState("operator")
  const [authError, setAuthError] = useState("")
  const [notif, setNotif] = useState<{ msg: string, type: 'info' | 'error' | 'success' } | null>(null)
  const [showPasswordWarning, setShowPasswordWarning] = useState(false)

  const showNotif = (msg: string, type: 'info' | 'error' | 'success' = 'info') => {
    setNotif({ msg, type })
    setTimeout(() => setNotif(null), 5000)
  }

  // Login Function
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setAuthError("")
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
        body: formData
      })

      if (!res.ok) throw new Error("Invalid credentials")

      const data = await res.json()
      setToken(data.access_token)
      if (username === "operator") setShowPasswordWarning(true)
      setIsLoading(false)
    } catch (err) {
      setAuthError("Login failed. Check backend credentials.")
      setIsLoading(false)
    }
  }

  // Fetch alarms from real TMF642 API — defined at component scope so SSE handler can call it
  const fetchAlarms = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/tmf-api/alarmManagement/v4/alarm`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })
      if (response.ok) {
        const data = await response.json()
        setAlarms(data)
      } else if (response.status === 401) {
        setToken(null) // Logout on 401
      }
    } catch (error) {
      console.error("Failed to fetch alarms:", error)
    }
  }

  // Task 5.1: Fetch scorecard KPIs (MTTR + Uptime) from real API
  const fetchScorecard = async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/autonomous/scorecard`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setScorecard({ avg_mttr: data.avg_mttr_minutes, uptime_pct: data.uptime_pct });
      }
    } catch (e) { console.error('Scorecard fetch failed:', e); }
  };

  // SSE for real-time alarm updates (Task 4.2 — replaces 10s polling)
  useEffect(() => {
    if (!token) return;

    // Initial fetches on connect
    fetchAlarms();
    fetchScorecard();

    // Open SSE stream for real-time push notifications
    const eventSource = new EventSource(
      `${API_BASE_URL}/api/v1/stream/alarms`,
      { withCredentials: false }
    );

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.event === 'alarms_updated') {
          fetchAlarms(); // Fetch fresh data when server signals a change
          fetchScorecard(); // Also refresh scorecard
        }
      } catch (e) {
        console.error('SSE parse error:', e);
      }
    };

    eventSource.onerror = (err) => {
      console.warn('SSE connection error, closing stream:', err);
      eventSource.close();
    };

    return () => eventSource.close(); // Cleanup on unmount or token change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);


  // Fetch capacity requests
  useEffect(() => {
    if (!token || activeView !== 'capacity') return

    async function fetchCapacity() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/capacity/`, {
          headers: { 'Authorization': `Bearer ${token}` }
        })
        if (response.ok) {
          const data = await response.json()
          setCapacityRequests(data)
        }
      } catch (error) {
        console.error("Failed to fetch capacity requests:", error)
      }
    }

    fetchCapacity()
  }, [token, activeView])

  // Fetch specific investment plan
  useEffect(() => {
    if (!token || !selectedRequest) return

    async function fetchPlan() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/capacity/${selectedRequest.id}/plan`, {
          headers: { 'Authorization': `Bearer ${token}` }
        })
        if (response.ok) {
          const data = await response.json()
          setInvestmentPlan(data)
        } else {
          setInvestmentPlan(null)
        }
      } catch (error) {
        console.error("Failed to fetch plan:", error)
      }
    }

    fetchPlan()
  }, [token, selectedRequest])

  const handleAcknowledge = async (id: string) => {
    if (!token) return
    try {
      showNotif("Acknowledging alarm...", "info")
      const response = await fetch(`${API_BASE_URL}/tmf-api/alarmManagement/v4/alarm/${id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ ackState: 'acknowledged' })
      })
      if (response.ok) {
        const updatedAlarm = await response.json()
        setAlarms(prev => prev.map(a => a.id === id ? updatedAlarm : a))
        setSelectedAlarm(updatedAlarm)
        showNotif("Alarm acknowledged successfully", "success")
      } else {
        const errData = await response.json().catch(() => ({}))
        showNotif(`Failed to acknowledge: ${errData.detail || response.statusText}`, "error")
      }
    } catch (error) {
      console.error("Failed to acknowledge alarm:", error)
      showNotif("Network error acknowledging alarm", "error")
    }
  }

  const handleSidebarClick = (view: string) => {
    if (view === 'alarms' || view === 'capacity') {
      setActiveView(view as any)
    } else {
      showNotif(`${view.charAt(0).toUpperCase() + view.slice(1)} view is coming in a future release`, "info")
    }
  }

  // LOGIN SCREEN
  if (!token) {
    return (
      <div className="min-h-screen bg-[#020617] text-slate-100 flex items-center justify-center p-6">
        <div className="glass p-8 rounded-2xl border-slate-800 w-full max-w-md space-y-6">
          <div className="flex flex-col items-center gap-2 mb-4">
            <Shield className="w-12 h-12 text-cyan-400" />
            <h1 className="text-2xl font-bold">Pedkai NOC Access</h1>
            <p className="text-slate-400 text-sm">Authorized Personnel Only</p>
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="text-xs uppercase font-bold text-slate-500">Operator ID</label>
              <input
                type="text"
                autoComplete="off"
                value={username}
                onChange={e => setUsername(e.target.value)}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg p-3 mt-1 focus:border-cyan-500 focus:outline-none transition-colors"
                name="operator-id-field"
              />
            </div>
            <div>
              <label className="text-xs uppercase font-bold text-slate-500">Passcode</label>
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg p-3 mt-1 focus:border-cyan-500 focus:outline-none transition-colors"
                name="passcode-field"
              />
            </div>

            {authError && (
              <div className="text-rose-400 text-sm flex items-center gap-2 bg-rose-900/20 p-3 rounded-lg border border-rose-900/50">
                <AlertCircle className="w-4 h-4" /> {authError}
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full bg-cyan-600 hover:bg-cyan-500 text-white font-bold py-3 rounded-lg transition-all glow active:scale-95 flex justify-center items-center gap-2"
            >
              {isLoading ? <Activity className="animate-spin w-5 h-5" /> : <Lock className="w-4 h-4" />}
              Init Session
            </button>
          </form>
        </div>
      </div>
    )
  }

  // DASHBOARD
  return (
    <div className="min-h-screen bg-[#020617] text-slate-100 p-6 flex gap-6 overflow-hidden relative">
      {/* Notifications Toast */}
      <AnimatePresence>
        {notif && (
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            className={cn(
              "fixed top-6 right-6 z-50 p-4 rounded-xl border shadow-2xl flex items-center gap-3 backdrop-blur-xl",
              notif.type === 'error' ? 'bg-rose-900/60 border-rose-500/50 text-rose-100' :
                notif.type === 'success' ? 'bg-emerald-900/60 border-emerald-500/50 text-emerald-100' :
                  'bg-cyan-900/60 border-cyan-500/50 text-cyan-100'
            )}
          >
            {notif.type === 'error' ? <AlertCircle className="w-5 h-5 text-rose-400" /> :
              notif.type === 'success' ? <CheckCircle className="w-5 h-5 text-emerald-400" /> :
                <Activity className="w-5 h-5 text-cyan-400" />}
            <span className="font-medium text-sm">{notif.msg}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Sidebar Navigation - RESTORED */}
      <nav className="w-16 glass rounded-2xl flex flex-col items-center py-8 gap-8 border-slate-800">
        <Shield className="text-cyan-400 w-8 h-8" />
        <div className="flex flex-col gap-6 flex-1">
          <Activity
            className={cn("w-6 h-6 cursor-pointer transition-colors", activeView === 'alarms' ? 'text-cyan-400' : 'text-slate-500 hover:text-cyan-400')}
            onClick={() => handleSidebarClick('alarms')}
          />
          <TrendingUp
            className={cn("w-6 h-6 cursor-pointer transition-colors", activeView === 'capacity' ? 'text-cyan-400' : 'text-slate-500 hover:text-cyan-400')}
            onClick={() => handleSidebarClick('capacity')}
          />
          <Network
            className="text-slate-500 w-6 h-6 hover:text-cyan-400 cursor-pointer transition-colors"
            onClick={() => handleSidebarClick('topology')}
          />
          <Database
            className="text-slate-500 w-6 h-6 hover:text-cyan-400 cursor-pointer transition-colors"
            onClick={() => handleSidebarClick('telelogs')}
          />
          <Cpu
            className="text-slate-500 w-6 h-6 hover:text-cyan-400 cursor-pointer transition-colors"
            onClick={() => handleSidebarClick('processing')}
          />
        </div>
      </nav>

      <main className="flex-1 flex flex-col gap-6 h-[calc(100vh-3rem)]">
        {/* Password Security Warning - NON-BLOCKING */}
        <AnimatePresence>
          {showPasswordWarning && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-4 flex items-center justify-between group"
            >
              <div className="flex items-center gap-3">
                <Shield className="w-5 h-5 text-rose-500" />
                <div>
                  <p className="text-sm font-bold text-rose-400 uppercase tracking-wider">Security Advisory: Default Password Active</p>
                  <p className="text-xs text-rose-400/70">Account 'operator' is using a standard passcode. Change recommended for production environments.</p>
                </div>
              </div>
              <button
                onClick={() => setShowPasswordWarning(false)}
                className="text-xs font-black uppercase text-rose-400 hover:text-white px-3 py-1 rounded-lg hover:bg-rose-500/20 transition-all"
              >
                Acknowledge
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Header Stats - RESTORED */}
        <header className="flex justify-between items-center bg-slate-900/40 p-6 rounded-2xl glass border-slate-800">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <Zap className="text-yellow-400 fill-yellow-400 w-5 h-5" />
              Pedkai NOC Command Center
            </h1>
            <p className="text-slate-400 text-sm">Real-time Autonomous Network Operations</p>
          </div>
          <div className="flex gap-4">
            <StatCard icon={<AlertCircle className="text-rose-500" />} label="Critical" value={alarms.filter((a: any) => a.perceivedSeverity === 'critical').length.toString()} />
            <StatCard icon={<Clock className="text-cyan-400" />} label="MTTR"
              value={scorecard?.avg_mttr != null ? `${Math.round(scorecard.avg_mttr)}m` : '—'} />
            <StatCard icon={<CheckCircle className="text-emerald-500" />} label="Uptime"
              value={scorecard?.uptime_pct != null ? `${scorecard.uptime_pct.toFixed(2)}%` : '—'} />
          </div>
        </header>

        <div className="flex-1 flex gap-6 min-h-0">
          {activeView === 'alarms' ? (
            <>
              {/* Alarm Ingress Feed */}
              <section className="w-[450px] flex flex-col glass rounded-2xl border-slate-800 overflow-hidden">
                <div className="p-4 border-b border-slate-800 bg-slate-900/60 flex justify-between items-center">
                  <h2 className="font-semibold text-sm uppercase tracking-wider text-slate-400">Alarm Ingress (TMF642)</h2>
                  <span className="px-2 py-0.5 bg-rose-500/20 text-rose-400 text-[10px] font-bold rounded-full border border-rose-500/30">
                    {alarms.filter(a => a.perceivedSeverity === 'critical').length} LIVE
                  </span>
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                  {isLoading ? (
                    <div className="flex justify-center p-8"><Activity className="animate-spin text-slate-500" /></div>
                  ) : alarms.length > 0 ? (
                    alarms.map((alarm) => (
                      <AlarmCard
                        key={alarm.id}
                        alarm={alarm}
                        isSelected={selectedAlarm?.id === alarm.id}
                        onClick={() => setSelectedAlarm(alarm)}
                      />
                    ))
                  ) : (
                    <div className="text-center p-8 text-slate-500 text-sm">No active alarms</div>
                  )}
                </div>
              </section>

              {/* Situation Analysis / SITREP — Task 5.2: extracted to SitrepPanel */}
              <SitrepPanel selectedAlarm={selectedAlarm} onAcknowledge={handleAcknowledge} />
            </>
          ) : (
            <>
              {/* Capacity Requests Feed */}
              <section className="w-[450px] flex flex-col glass rounded-2xl border-slate-800 overflow-hidden">
                <div className="p-4 border-b border-slate-800 bg-slate-900/60 flex justify-between items-center">
                  <h2 className="font-semibold text-sm uppercase tracking-wider text-slate-400">Regional Densification</h2>
                  <TrendingUp className="w-4 h-4 text-cyan-400" />
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                  {capacityRequests.length > 0 ? (
                    capacityRequests.map((req) => (
                      <div
                        key={req.id}
                        onClick={() => setSelectedRequest(req)}
                        className={cn(
                          "p-4 rounded-xl cursor-pointer transition-all border",
                          selectedRequest?.id === req.id ? "bg-cyan-500/10 border-cyan-500/50" : "bg-slate-900/40 border-slate-800"
                        )}
                      >
                        <h4 className="font-bold text-white uppercase text-sm">{req.region_name}</h4>
                        <div className="flex justify-between items-center mt-2">
                          <span className="text-[10px] text-slate-500 font-bold">${req.budget_limit.toLocaleString()}</span>
                          <span className={cn(
                            "text-[10px] font-black px-2 py-0.5 rounded",
                            req.status === 'completed' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-yellow-500/20 text-yellow-400'
                          )}>{req.status}</span>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="text-center p-8 text-slate-500 text-sm">No investment requests</div>
                  )}
                </div>
              </section>

              {/* Investment Plan Detail */}
              <section className="flex-1 glass rounded-2xl border-slate-800 flex flex-col p-8">
                {selectedRequest ? (
                  investmentPlan ? (
                    <div className="space-y-8">
                      <div className="flex justify-between items-start">
                        <div>
                          <h2 className="text-3xl font-bold text-white">OPTIMIZED INVESTMENT PLAN</h2>
                          <p className="text-slate-400 mt-1 uppercase tracking-widest text-xs">Request ID: {selectedRequest.id}</p>
                        </div>
                        <div className="bg-emerald-500/10 border border-emerald-500/20 p-4 rounded-xl text-right">
                          <p className="text-xs font-bold text-slate-500 uppercase">Estimated ROI</p>
                          <p className="text-2xl font-black text-emerald-400">+{investmentPlan.expected_kpi_improvement.toFixed(1)}%</p>
                        </div>
                      </div>

                      <div className="bg-slate-900/50 p-6 rounded-xl border border-slate-800">
                        <h3 className="text-cyan-400 text-xs font-black uppercase mb-4">Strategic Rationale</h3>
                        <p className="text-slate-300 leading-relaxed">{investmentPlan.rationale}</p>
                      </div>

                      <div className="space-y-4">
                        <h3 className="text-cyan-400 text-xs font-black uppercase">Optimized Site Placements</h3>
                        <div className="grid grid-cols-1 gap-3">
                          {investmentPlan.site_placements.map((site: any, idx: number) => (
                            <div key={idx} className="flex items-center justify-between bg-white/5 p-4 rounded-xl border border-white/10 group hover:border-cyan-500/50 transition-colors">
                              <div className="flex items-center gap-4">
                                <div className="p-3 bg-slate-900 rounded-lg group-hover:bg-cyan-500/20 transition-colors">
                                  <MapPin className="w-5 h-5 text-cyan-400" />
                                </div>
                                <div>
                                  <p className="font-bold text-white">{site.name}</p>
                                  <p className="text-[10px] text-slate-500">{site.lat}, {site.lon}</p>
                                </div>
                              </div>
                              <div className="text-right">
                                <p className="font-black text-white text-lg">${site.cost.toLocaleString()}</p>
                                <span className="text-[10px] text-slate-500 font-bold tracking-widest uppercase">{site.backhaul || 'Fiber'}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex-1 flex flex-col items-center justify-center text-slate-500">
                      <Activity className="animate-spin w-12 h-12 mb-4" />
                      <p>Generating optimized investment plan...</p>
                    </div>
                  )
                ) : (
                  <div className="flex-1 flex flex-col items-center justify-center text-slate-500 opacity-50">
                    <TrendingUp className="w-24 h-24 mb-4" />
                    <p className="text-lg tracking-widest uppercase font-black">Select a region to optimize</p>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  )
}

// StatCard, AlarmCard, and SitrepPanel are now in frontend/app/components/ (Task 5.2)
