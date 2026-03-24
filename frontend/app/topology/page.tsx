"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { ZoomIn, ZoomOut, Maximize2, Search, ArrowRight, Layers, Network } from "lucide-react";
import { useAuth } from "@/app/context/AuthContext";
import { useTheme } from "@/app/context/ThemeContext";

interface TopologyEntity {
  id: string;
  name: string;
  entity_type: string;
  status: string;
  external_id?: string;
  vendor?: string;
  zone?: string;
  properties?: Record<string, any>;
}

interface TopologyRelationship {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
}

interface SearchResult {
  id: string;
  name: string;
  entity_type: string;
  external_id: string;
  status: string;
}

const TYPE_COLORS: Record<string, string> = {
  site: "#3b82f6", gnodeb: "#8b5cf6", enodeb: "#7c3aed", cell: "#06b6d4",
  sector: "#0891b2", router: "#f59e0b", switch: "#f97316", core_router: "#ea580c",
  aggregation_switch: "#d97706", olt: "#84cc16", onu: "#22c55e", mme: "#ec4899",
  sgw: "#db2777", pgw: "#be185d", bsc: "#a855f7", rnc: "#9333ea", msc: "#c026d3",
  hlr: "#e11d48", pcrf: "#f43f5e", upf: "#14b8a6", smf: "#0d9488", amf: "#0ea5e9",
  nrf: "#6366f1", microwave_link: "#78716c", fiber_link: "#a3e635", transmission: "#facc15",
  server: "#3b82f6", firewall: "#ef4444", ids: "#f59e0b", workstation: "#10b981",
  dns_server: "#ec4899", mail_server: "#f97316", web_server: "#6366f1", database: "#14b8a6",
  emergency_service: "#ef4444", default: "#64748b",
};

function getColor(entityType: string): string {
  const key = entityType.toLowerCase().replace(/[\s-]/g, "_");
  return TYPE_COLORS[key] ?? TYPE_COLORS.default;
}

const STATUS_RING: Record<string, string> = {
  critical: "#ef4444", degraded: "#f59e0b", down: "#ef4444", active: "#22c55e",
  operational: "#22c55e", in_service: "#22c55e", maintenance: "#f59e0b", unknown: "#64748b",
};

export default function TopologyPage() {
  const { tenantId, token, authFetch } = useAuth();
  const { theme } = useTheme();
  const isLight = theme === "light";
  const searchParams = useSearchParams();

  // Search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  
  // Graph state
  const [seedId, setSeedId] = useState<string | null>(null);
  const [hops, setHops] = useState(2);
  const [entities, setEntities] = useState<TopologyEntity[]>([]);
  const [relationships, setRelationships] = useState<TopologyRelationship[]>([]);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Layer filter state
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [showInferred, setShowInferred] = useState(true);
  // Shadow topology
  const [shadowEntities, setShadowEntities] = useState<TopologyEntity[]>([]);
  const [shadowRelationships, setShadowRelationships] = useState<TopologyRelationship[]>([]);

  // View state
  const [selectedEntity, setSelectedEntity] = useState<TopologyEntity | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const dragging = useRef({ active: false, lastX: 0, lastY: 0, node: null as string | null });

  // 1. Search Debounce Effect
  useEffect(() => {
    if (!tenantId || !token) return;
    if (searchQuery.length < 2) {
      setSearchResults([]);
      return;
    }
    
    const delay = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await authFetch(
          `/api/v1/topology/${encodeURIComponent(tenantId)}/search?q=${encodeURIComponent(searchQuery)}`,
        );
        if (res.ok) {
          const data = await res.json();
          setSearchResults(data.results || []);
        }
      } catch (e) {
        console.error("Search failed:", e);
      } finally {
        setIsSearching(false);
      }
    }, 400);
    
    return () => clearTimeout(delay);
  }, [searchQuery, tenantId, token]);

  // 1b. Auto-seed from URL entity_id param (e.g. coming from Incidents page)
  useEffect(() => {
    if (!tenantId || !token) return;
    const entityId = searchParams.get("entity_id");
    if (entityId) setSeedId(entityId);
  }, [tenantId, token, searchParams]);

  // 2. Fetch Neighborhood Graph
  const fetchGraph = useCallback(async (seed: string, hopCount: number) => {
    if (!tenantId || !token) return;
    setLoadingGraph(true);
    setError(null);
    try {
      const res = await authFetch(
        `/api/v1/topology/${encodeURIComponent(tenantId)}/neighborhood/${encodeURIComponent(seed)}?hops=${hopCount}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      
      const mappedEntities = (data.entities || []).map((e: any) => ({
        ...e,
        status: e.properties?.status ?? e.status ?? "unknown",
        external_id: e.external_id ?? e.id,
      }));
      
      setEntities(mappedEntities);
      setRelationships(data.relationships || []);
      
      // Auto-select the seed node
      const seedNode = mappedEntities.find((e: any) => e.id === seed);
      if (seedNode) setSelectedEntity(seedNode);

      // Fetch shadow topology overlay
      try {
        const shadowRes = await authFetch(
          `/api/v1/topology/${encodeURIComponent(tenantId)}/neighborhood-with-shadow/${encodeURIComponent(seed)}?hops=${hopCount}`,
        );
        if (shadowRes.ok) {
          const shadowData = await shadowRes.json();
          setShadowEntities((shadowData.shadow_entities || []).map((e: any) => ({
            ...e,
            status: "inferred",
          })));
          setShadowRelationships(shadowData.shadow_relationships || []);
        }
      } catch {
        // Shadow data optional — fail silently
        setShadowEntities([]);
        setShadowRelationships([]);
      }

    } catch (e: any) {
      setError(e.message);
      setEntities([]);
      setRelationships([]);
    } finally {
      setLoadingGraph(false);
    }
  }, [tenantId, token]);

  // Handle seed change or hop change
  useEffect(() => {
    if (seedId) fetchGraph(seedId, hops);
  }, [seedId, hops, fetchGraph]);

  // 3. Force-Directed Layout Simulation (Simple Iterative)
  useEffect(() => {
    if (entities.length === 0) {
      setPositions({});
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) return;

    // Use a fixed simulation centre
    const cx = canvas.clientWidth / 2;
    const cy = canvas.clientHeight / 2;
    
    // Initialize positions randomly around center
    const newPos = { ...positions };
    entities.forEach((e) => {
      if (!newPos[e.id]) {
        // If it's the seed, put it dead centre
        if (e.id === seedId) {
          newPos[e.id] = { x: cx, y: cy };
        } else {
          const angle = Math.random() * Math.PI * 2;
          const r = 50 + Math.random() * 200;
          newPos[e.id] = { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r };
        }
      }
    });

    // Run simple force simulation loops synchronously for instant display
    const REPULSION = 2000;
    const SPRING_LEN = 80;
    const SPRING_K = 0.05;
    
    // Convert to arrays for faster iteration
    const posEntries = Object.entries(newPos);
    
    // 50 iterations feels snappy enough
    for (let iter = 0; iter < 50; iter++) {
      const forces: Record<string, { fx: number, fy: number }> = {};
      
      posEntries.forEach(([id]) => { forces[id] = { fx: 0, fy: 0 }; });
      
      // Repulsion (n^2)
      for (let i = 0; i < posEntries.length; i++) {
        const idA = posEntries[i][0];
        const a = newPos[idA];
        for (let j = i + 1; j < posEntries.length; j++) {
          const idB = posEntries[j][0];
          const b = newPos[idB];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const distSq = dx * dx + dy * dy;
          if (distSq > 0 && distSq < 90000) { // cutoff
            const dist = Math.sqrt(distSq);
            const force = REPULSION / distSq;
            forces[idA].fx += (dx / dist) * force;
            forces[idA].fy += (dy / dist) * force;
            forces[idB].fx -= (dx / dist) * force;
            forces[idB].fy -= (dy / dist) * force;
          }
        }
      }
      
      // Attraction (springs)
      relationships.forEach(r => {
        const a = newPos[r.source_entity_id];
        const b = newPos[r.target_entity_id];
        if (a && b) {
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist > 0) {
            const force = (dist - SPRING_LEN) * SPRING_K;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            forces[r.source_entity_id].fx += fx;
            forces[r.source_entity_id].fy += fy;
            forces[r.target_entity_id].fx -= fx;
            forces[r.target_entity_id].fy -= fy;
          }
        }
      });
      
      // Gravity to center (keeps graph contained)
      posEntries.forEach(([id]) => {
        const dx = cx - newPos[id].x;
        const dy = cy - newPos[id].y;
        forces[id].fx += dx * 0.01;
        forces[id].fy += dy * 0.01;
      });
      
      // Apply forces
      posEntries.forEach(([id]) => {
        // Strongly pin the seed
        if (id === seedId) {
          newPos[id].x = cx;
          newPos[id].y = cy;
        } else {
          newPos[id].x += forces[id].fx;
          newPos[id].y += forces[id].fy;
        }
      });
    }

    setPositions(newPos);
    // Center pan/zoom when graph changes
    setPan({ x: 0, y: 0 });
    setZoom(1);
    
  }, [entities, relationships, seedId]);

  // 4. Draw Canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || Object.keys(positions).length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);

    // Fill canvas background based on theme
    ctx.fillStyle = isLight ? "#f0f4f8" : "#06203b";
    ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);

    ctx.save();
    ctx.translate(pan.x, pan.y);
    ctx.scale(zoom, zoom);

    // Draw shadow (inferred) edges — dashed lines
    if (showInferred) {
      ctx.strokeStyle = isLight ? "rgba(139,92,246,0.5)" : "rgba(139,92,246,0.6)";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      shadowRelationships.forEach((rel) => {
        const from = positions[rel.source_entity_id];
        const to = positions[rel.target_entity_id];
        if (from && to) {
          ctx.beginPath();
          ctx.moveTo(from.x, from.y);
          ctx.lineTo(to.x, to.y);
          ctx.stroke();
        }
      });
      ctx.setLineDash([]);
    }

    // Build visible node set based on hiddenTypes filter
    const entMap = new Map(entities.map((e) => [e.id, e]));
    const visibleNodes = new Set<string>();
    entities.forEach((e) => {
      if (!hiddenTypes.has(e.entity_type)) visibleNodes.add(e.id);
    });

    // Draw edges (only between visible nodes)
    ctx.strokeStyle = isLight ? "rgba(15,23,42,0.2)" : "rgba(0,212,255,0.45)";
    ctx.lineWidth = 1.5;
    relationships.forEach((rel) => {
      if (!visibleNodes.has(rel.source_entity_id) || !visibleNodes.has(rel.target_entity_id)) return;
      const from = positions[rel.source_entity_id];
      const to = positions[rel.target_entity_id];
      if (from && to) {
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
      }
    });

    // Draw nodes (only visible types)
    Object.entries(positions).forEach(([id, pos]) => {
      const ent = entMap.get(id);
      if (!ent || !visibleNodes.has(id)) return;
      
      const isSeed = id === seedId;
      const isSelected = selectedEntity?.id === id;
      const r = isSeed ? 14 : 10; // Seed is bigger

      // Status ring
      const ringColor = STATUS_RING[ent.status] ?? STATUS_RING.unknown;
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, r + 3, 0, Math.PI * 2);
      ctx.fillStyle = ringColor;
      ctx.globalAlpha = isSelected || isSeed ? 1 : 0.5;
      ctx.fill();
      ctx.globalAlpha = 1;

      // Node fill
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, r, 0, Math.PI * 2);
      ctx.fillStyle = getColor(ent.entity_type);
      ctx.fill();

      if (isSelected || isSeed) {
        ctx.strokeStyle = isSeed ? "#fbbf24" : (isLight ? "#0f172a" : "#fff"); // Amber outline for seed
        ctx.lineWidth = isSeed ? 3 : 2;
        ctx.stroke();
      }

      // Label (only at sufficient zoom or if seed/selected)
      if (zoom >= 0.5 || isSelected || isSeed) {
        ctx.fillStyle = isSelected || isSeed ? (isLight ? "#0f172a" : "#fff") : (isLight ? "#334155" : "#cbd5e1");
        const fontSize = Math.max(8, Math.min(isSeed ? 12 : 11, 9 / zoom));
        ctx.font = `${isSeed || isSelected ? 'bold ' : ''}${fontSize}px sans-serif`;
        ctx.textAlign = "center";
        const label = ent.name.length > 20 ? ent.name.slice(0, 18) + "…" : ent.name;
        ctx.fillText(label, pos.x, pos.y + r + 14);
      }
    });

    ctx.restore();
  }, [positions, relationships, entities, zoom, pan, selectedEntity, seedId, shadowRelationships, showInferred, hiddenTypes, isLight]);

  // 5. Canvas Interactions
  const handleCanvasClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left - pan.x) / zoom;
    const my = (e.clientY - rect.top - pan.y) / zoom;
    
    // Find clicked node
    const entMap = new Map(entities.map((ent) => [ent.id, ent]));
    let found: TopologyEntity | null = null;
    for (const [id, pos] of Object.entries(positions)) {
      const dx = mx - pos.x;
      const dy = my - pos.y;
      const r = id === seedId ? 14 : 10;
      if (dx * dx + dy * dy < (r + 4) * (r + 4)) {
        found = entMap.get(id) ?? null;
        break;
      }
    }
    
    if (found) {
      setSelectedEntity(found);
    }
  }, [entities, positions, zoom, pan, seedId]);

  const handleMouseDown = (e: React.MouseEvent) => {
    dragging.current = { active: true, lastX: e.clientX, lastY: e.clientY, node: null };
    
    // Check if clicking a node to drag it
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left - pan.x) / zoom;
    const my = (e.clientY - rect.top - pan.y) / zoom;
    
    for (const [id, pos] of Object.entries(positions)) {
      const dx = mx - pos.x;
      const dy = my - pos.y;
      if (dx * dx + dy * dy < 196) {
        dragging.current.node = id;
        break;
      }
    }
  };
  
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current.active) return;
    
    if (dragging.current.node) {
      // Drag individual node
      const dx = (e.clientX - dragging.current.lastX) / zoom;
      const dy = (e.clientY - dragging.current.lastY) / zoom;
      setPositions(prev => ({
        ...prev,
        [dragging.current.node!]: {
          x: prev[dragging.current.node!].x + dx,
          y: prev[dragging.current.node!].y + dy
        }
      }));
    } else {
      // Pan canvas
      setPan((p) => ({
        x: p.x + e.clientX - dragging.current.lastX,
        y: p.y + e.clientY - dragging.current.lastY,
      }));
    }
    dragging.current.lastX = e.clientX;
    dragging.current.lastY = e.clientY;
  };
  
  const handleMouseUp = () => { dragging.current.active = false; };
  
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.min(4, Math.max(0.15, z - e.deltaY * 0.001)));
  };


  return (
    <div className="flex h-[calc(100vh-64px)] overflow-hidden">
      
      {/* ── Sidebar: Search & Explorer ── */}
      <div className="w-80 border-r border-cyan-900/40 bg-[#0a2d4a] flex flex-col z-10">
        <div className="p-4 border-b border-cyan-900/40 space-y-4 shadow-sm bg-[#06203b]">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Layers className="w-5 h-5 text-cyan-400" />
              Topology Explorer
            </h2>
            <p className="text-xs text-white/80 mt-1 leading-relaxed">
              Search for an entity to seed the graph, then explore its neighborhood.
            </p>
          </div>

          <div className="relative">
            <Search className="w-4 h-4 text-white/40 absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search by name, ID, or type..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 rounded-lg bg-[#0a2d4a] border border-cyan-900/50 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-400"
            />
            <p className="text-[10px] text-white/70 mt-1">
              Try: SITE, GNODEB, NR_CELL, ENB, ROUTER, OLT — or paste an external ID
            </p>
          </div>
        </div>

        {/* Search Results */}
        {searchQuery.length > 0 && !seedId && (
          <div className="flex-1 overflow-y-auto bg-[#0a2d4a] shadow-inner">
            {isSearching ? (
              <div className="p-4 text-xs text-white animate-pulse text-center">Searching...</div>
            ) : searchResults.length > 0 ? (
              <div className="divide-y divide-cyan-900/20">
                {searchResults.map(res => (
                  <button
                    key={res.id}
                    onClick={() => {
                        setSeedId(res.id);
                        setSearchQuery("");
                    }}
                    className="w-full text-left px-4 py-3 hover:bg-white/5 transition-colors group"
                  >
                    <div className="font-medium text-sm text-white group-hover:text-cyan-400 flex items-center justify-between">
                      <span className="truncate pr-2">{res.name}</span>
                      <ArrowRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                    </div>
                    <div className="text-xs text-white/80 mt-0.5 flex items-center gap-2">
                      <span className="px-1.5 rounded bg-[#06203b] text-white font-mono text-[10px]">
                        {res.entity_type}
                      </span>
                      <span className="truncate">{res.external_id}</span>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="p-4 text-xs text-white text-center">No entities found.</div>
            )}
          </div>
        )}

        {/* Graph Controls (Visible when active) */}
        {seedId && !searchQuery && (
          <div className="flex-1 flex flex-col">
            <div className="p-4 bg-cyan-900/10 border-b border-cyan-900/30">
              <div className="text-xs text-white uppercase tracking-wider font-semibold mb-1">Seed Node</div>
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-bold text-white break-all">
                    {entities.find(e => e.id === seedId)?.name || seedId}
                  </div>
                  <div className="text-xs text-white/80 mt-0.5">
                    {entities.find(e => e.id === seedId)?.entity_type || "Entity"}
                  </div>
                </div>
                <button
                  onClick={() => { setSeedId(null); setEntities([]); setRelationships([]); }}
                  className="text-[10px] text-white/80 hover:text-white underline underline-offset-2 shrink-0 ml-2"
                >
                  Clear
                </button>
              </div>
              
              <div className="mt-4 space-y-2">
                <div className="flex items-center justify-between text-xs text-white">
                  <span>Neighborhood Depth</span>
                  <span className="font-bold text-white">{hops} {hops === 1 ? 'hop' : 'hops'}</span>
                </div>
                <input 
                  type="range" 
                  min="1" max="4" 
                  value={hops}
                  onChange={(e) => setHops(parseInt(e.target.value))}
                  className="w-full accent-cyan-400"
                />
              </div>
            </div>
            
            <div className="px-4 py-3 bg-[#06203b] border-b border-cyan-900/40 text-xs flex justify-between text-white font-medium">
              <span>{entities.length} Nodes</span>
              <span>{relationships.length} Edges</span>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              {/* Entity types legend for current view */}
              <p className="text-[10px] uppercase tracking-wider text-white font-bold mb-2">
                Types in View
              </p>
              <div className="flex flex-wrap gap-1.5">
                {[...new Set(entities.map((e) => e.entity_type))].sort().map((t) => (
                  <span key={t} className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white">
                    <span className="w-2 h-2 rounded-full mr-1.5 shrink-0" style={{ backgroundColor: getColor(t) }} />
                    {t}
                  </span>
                ))}
              </div>

              {/* Layer Filter */}
              <div className="mt-4">
                <p className="text-[10px] uppercase tracking-wider text-white font-bold mb-2">
                  Layer Filter
                </p>
                <label className="flex items-center gap-2 text-xs text-white/80 mb-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={showInferred}
                    onChange={(e) => setShowInferred(e.target.checked)}
                    className="accent-violet-500"
                  />
                  Show inferred links
                </label>
                <div className="space-y-1 max-h-40 overflow-y-auto">
                  {[...new Set(entities.map((e) => e.entity_type))].sort().map((t) => (
                    <label key={t} className="flex items-center gap-2 text-[11px] text-white/80 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!hiddenTypes.has(t)}
                        onChange={(e) => {
                          const isChecked = e.target.checked;
                          setHiddenTypes(prev => {
                            const next = new Set(prev);
                            if (isChecked) {
                              next.delete(t);
                            } else {
                              next.add(t);
                            }
                            return next;
                          });
                        }}
                        className="accent-cyan-400"
                      />
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: getColor(t) }} />
                      {t}
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Canvas area ── */}
      <div className="flex-1 relative bg-[#020d18]">
        {!seedId ? (
          <div className="absolute inset-0 flex items-center justify-center flex-col text-white">
            <Network className="w-16 h-16 mb-4 opacity-40" />
            <p className="text-lg">Use the sidebar to search for an entity</p>
            <p className="text-sm mt-1 text-white/70">Explore the topology graph outward from a specific node</p>
          </div>
        ) : loadingGraph && entities.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-cyan-400 animate-pulse">
            Loading neighborhood graph...
          </div>
        ) : (
          <>
            <canvas
              ref={canvasRef}
              className="w-full h-full cursor-grab active:cursor-grabbing"
              onClick={handleCanvasClick}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              onWheel={handleWheel}
            />

            {/* Zoom controls */}
            <div className="absolute top-4 right-4 flex flex-col gap-1 z-10">
              <button
                onClick={() => setZoom((z) => Math.min(4, z * 1.3))}
                className="p-2 rounded-lg bg-[#0a2d4a] border border-cyan-900/40 text-slate-200 hover:text-white hover:bg-[#0d3b5e] shadow-lg"
              >
                <ZoomIn className="w-4 h-4" />
              </button>
              <button
                onClick={() => setZoom((z) => Math.max(0.15, z / 1.3))}
                className="p-2 rounded-lg bg-[#0a2d4a] border border-cyan-900/40 text-slate-200 hover:text-white hover:bg-[#0d3b5e] shadow-lg"
              >
                <ZoomOut className="w-4 h-4" />
              </button>
              <button
                onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}
                className="p-2 rounded-lg bg-[#0a2d4a] border border-cyan-900/40 text-slate-200 hover:text-white hover:bg-[#0d3b5e] shadow-lg"
              >
                <Maximize2 className="w-4 h-4" />
              </button>
            </div>

            {/* Selection detail panel */}
            {selectedEntity && (
              <div className="absolute bottom-4 left-4 right-4 max-w-md bg-[#0a2d4a] border border-cyan-900/40 rounded-xl p-4 shadow-2xl z-10">
                <div className="flex items-center gap-3 mb-3">
                  <span
                    className="w-4 h-4 rounded-full flex-shrink-0"
                    style={{ backgroundColor: getColor(selectedEntity.entity_type) }}
                  />
                  <h3 className="text-white font-bold text-lg truncate flex-1">
                    {selectedEntity.name}
                  </h3>
                  {selectedEntity.id === seedId && (
                    <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px] font-bold uppercase">
                      Seed
                    </span>
                  )}
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      selectedEntity.status === "active" ? "bg-green-900/50 text-green-400 border border-green-700/50" :
                      selectedEntity.status === "critical" ? "bg-red-900/50 text-red-400 border border-red-700/50" :
                      "bg-slate-700/50 text-slate-200 border border-slate-600/50"
                    }`}
                  >
                    {selectedEntity.status}
                  </span>
                </div>
                
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm bg-[#06203b] rounded-lg p-3 border border-cyan-900/30">
                  <span className="text-white/60">Type</span>
                  <span className="text-white font-mono text-xs py-0.5">{selectedEntity.entity_type}</span>

                  {selectedEntity.external_id && selectedEntity.external_id !== selectedEntity.id && (
                    <>
                      <span className="text-white/60">External ID</span>
                      <span className="text-white font-mono text-[10px] truncate" title={selectedEntity.external_id}>
                        {selectedEntity.external_id}
                      </span>
                    </>
                  )}

                  <span className="text-white/60">Edges in view</span>
                  <span className="text-white">
                    {relationships.filter((r) => r.source_entity_id === selectedEntity.id || r.target_entity_id === selectedEntity.id).length}
                  </span>
                </div>
                
                {selectedEntity.id !== seedId && (
                  <button
                    onClick={() => { setSeedId(selectedEntity.id); setHops(2); }}
                    className="w-full mt-3 py-1.5 rounded bg-[#06203b] hover:bg-[#0d3b5e] border border-white/25 transition-colors text-xs font-semibold text-white flex items-center justify-center gap-1.5"
                  >
                    <Search className="w-3.5 h-3.5" /> Set as new seed
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
