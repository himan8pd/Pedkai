"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { useAuth } from "@/app/context/AuthContext";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
}

const TYPE_COLORS: Record<string, string> = {
  // Telco2 entity types
  site: "#3b82f6",
  gnodeb: "#8b5cf6",
  enodeb: "#7c3aed",
  cell: "#06b6d4",
  sector: "#0891b2",
  router: "#f59e0b",
  switch: "#f97316",
  core_router: "#ea580c",
  aggregation_switch: "#d97706",
  olt: "#84cc16",
  onu: "#22c55e",
  mme: "#ec4899",
  sgw: "#db2777",
  pgw: "#be185d",
  bsc: "#a855f7",
  rnc: "#9333ea",
  msc: "#c026d3",
  hlr: "#e11d48",
  pcrf: "#f43f5e",
  upf: "#14b8a6",
  smf: "#0d9488",
  amf: "#0ea5e9",
  nrf: "#6366f1",
  microwave_link: "#78716c",
  fiber_link: "#a3e635",
  transmission: "#facc15",
  // CasinoLimit / generic types
  server: "#3b82f6",
  firewall: "#ef4444",
  ids: "#f59e0b",
  workstation: "#10b981",
  dns_server: "#ec4899",
  mail_server: "#f97316",
  web_server: "#6366f1",
  database: "#14b8a6",
  emergency_service: "#ef4444",
  default: "#64748b",
};

function getColor(entityType: string): string {
  const key = entityType.toLowerCase().replace(/[\s-]/g, "_");
  return TYPE_COLORS[key] ?? TYPE_COLORS.default;
}

const STATUS_RING: Record<string, string> = {
  critical: "#ef4444",
  degraded: "#f59e0b",
  down: "#ef4444",
  active: "#22c55e",
  operational: "#22c55e",
  in_service: "#22c55e",
  maintenance: "#f59e0b",
  unknown: "#64748b",
};

export default function TopologyPage() {
  const { tenantId, token } = useAuth();
  const [entities, setEntities] = useState<TopologyEntity[]>([]);
  const [relationships, setRelationships] = useState<TopologyRelationship[]>(
    [],
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<TopologyEntity | null>(
    null,
  );
  const [filter, setFilter] = useState("");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [positions, setPositions] = useState<
    Record<string, { x: number; y: number }>
  >({});
  const dragging = useRef<{ active: boolean; lastX: number; lastY: number }>({
    active: false,
    lastX: 0,
    lastY: 0,
  });

  // Fetch topology
  useEffect(() => {
    if (!tenantId) return;
    async function fetchTopology() {
      try {
        const res = await fetch(
          `${API_BASE_URL}/api/v1/topology/${encodeURIComponent(tenantId)}`,
          {
            headers: { Authorization: `Bearer ${token}` },
          },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        // Map entities, resolving status from properties if present
        const mapped = (data.entities ?? []).map((e: any) => ({
          ...e,
          status: e.properties?.status ?? e.status ?? "unknown",
          external_id: e.external_id ?? e.id,
        }));
        setEntities(mapped);
        setRelationships(data.relationships ?? []);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    fetchTopology();
  }, [tenantId, token]);

  // Layout entities in a force-like grid grouped by type
  useEffect(() => {
    if (entities.length === 0) return;
    const grouped: Record<string, TopologyEntity[]> = {};
    entities.forEach((e) => {
      const t = e.entity_type || "unknown";
      if (!grouped[t]) grouped[t] = [];
      grouped[t].push(e);
    });

    const pos: Record<string, { x: number; y: number }> = {};
    const types = Object.keys(grouped);
    const cols = Math.ceil(Math.sqrt(types.length));
    const groupSpacingX = 420;
    const groupSpacingY = 350;

    types.forEach((type, gi) => {
      const col = gi % cols;
      const row = Math.floor(gi / cols);
      const baseX = 100 + col * groupSpacingX;
      const baseY = 100 + row * groupSpacingY;

      const items = grouped[type];
      const itemCols = Math.ceil(Math.sqrt(items.length));
      items.forEach((ent, i) => {
        const ic = i % itemCols;
        const ir = Math.floor(i / itemCols);
        pos[ent.id] = {
          x: baseX + ic * 60,
          y: baseY + ir * 50,
        };
      });
    });
    setPositions(pos);
  }, [entities]);

  // Draw canvas
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

    ctx.save();
    ctx.translate(pan.x, pan.y);
    ctx.scale(zoom, zoom);

    // Draw edges
    ctx.strokeStyle = "rgba(100,116,139,0.18)";
    ctx.lineWidth = 0.4;
    relationships.forEach((rel) => {
      const from = positions[rel.source_entity_id];
      const to = positions[rel.target_entity_id];
      if (from && to) {
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
      }
    });

    // Draw nodes
    const entMap = new Map(entities.map((e) => [e.id, e]));
    Object.entries(positions).forEach(([id, pos]) => {
      const ent = entMap.get(id);
      if (!ent) return;
      const r = 10;
      const isSelected = selectedEntity?.id === id;

      // Status ring
      const ringColor = STATUS_RING[ent.status] ?? STATUS_RING.unknown;
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, r + 3, 0, Math.PI * 2);
      ctx.fillStyle = ringColor;
      ctx.globalAlpha = isSelected ? 1 : 0.5;
      ctx.fill();
      ctx.globalAlpha = 1;

      // Node fill
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, r, 0, Math.PI * 2);
      ctx.fillStyle = getColor(ent.entity_type);
      ctx.fill();

      if (isSelected) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Label (only at sufficient zoom)
      if (zoom >= 0.5) {
        ctx.fillStyle = "#cbd5e1";
        ctx.font = `${Math.max(8, Math.min(11, 9 / zoom))}px sans-serif`;
        ctx.textAlign = "center";
        const label =
          ent.name.length > 20 ? ent.name.slice(0, 18) + "…" : ent.name;
        ctx.fillText(label, pos.x, pos.y + r + 14);
      }
    });

    ctx.restore();
  }, [positions, relationships, entities, zoom, pan, selectedEntity]);

  // Canvas click → select entity
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const mx = (e.clientX - rect.left - pan.x) / zoom;
      const my = (e.clientY - rect.top - pan.y) / zoom;
      const entMap = new Map(entities.map((ent) => [ent.id, ent]));
      let found: TopologyEntity | null = null;
      for (const [id, pos] of Object.entries(positions)) {
        const dx = mx - pos.x;
        const dy = my - pos.y;
        if (dx * dx + dy * dy < 196) {
          found = entMap.get(id) ?? null;
          break;
        }
      }
      setSelectedEntity(found);
    },
    [entities, positions, zoom, pan],
  );

  // Pan via mouse drag
  const handleMouseDown = (e: React.MouseEvent) => {
    dragging.current = { active: true, lastX: e.clientX, lastY: e.clientY };
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current.active) return;
    setPan((p) => ({
      x: p.x + e.clientX - dragging.current.lastX,
      y: p.y + e.clientY - dragging.current.lastY,
    }));
    dragging.current.lastX = e.clientX;
    dragging.current.lastY = e.clientY;
  };
  const handleMouseUp = () => {
    dragging.current.active = false;
  };

  // Zoom controls
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.min(4, Math.max(0.15, z - e.deltaY * 0.001)));
  };

  // Entity types legend
  const entityTypes = [...new Set(entities.map((e) => e.entity_type))].sort();

  // Filtered list for sidebar
  const filteredEntities = filter
    ? entities.filter(
        (e) =>
          e.name.toLowerCase().includes(filter.toLowerCase()) ||
          e.entity_type.toLowerCase().includes(filter.toLowerCase()),
      )
    : entities;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-gray-400 animate-pulse text-lg">
          Loading topology…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 space-y-4">
        <h1 className="text-3xl font-bold text-white">Topology</h1>
        <div className="p-4 rounded-lg bg-red-900/50 border border-red-700 text-red-200">
          Failed to load topology: {error}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-64px)]">
      {/* Sidebar */}
      <div className="w-72 border-r border-gray-800 bg-gray-900/50 flex flex-col overflow-hidden">
        <div className="p-4 border-b border-gray-800">
          <h2 className="text-lg font-bold text-white mb-2">Topology</h2>
          <p className="text-xs text-gray-500 mb-3">
            {entities.length} entities · {relationships.length} edges
          </p>
          <input
            type="text"
            placeholder="Filter entities…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full px-3 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        {/* Legend */}
        <div className="px-4 py-2 border-b border-gray-800">
          <p className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-1">
            Types
          </p>
          <div className="flex flex-wrap gap-1">
            {entityTypes.map((t) => (
              <span
                key={t}
                className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300"
              >
                <span
                  className="w-2 h-2 rounded-full mr-1 inline-block"
                  style={{ backgroundColor: getColor(t) }}
                />
                {t}
              </span>
            ))}
          </div>
        </div>

        {/* Entity list */}
        <div className="flex-1 overflow-y-auto">
          {filteredEntities.slice(0, 200).map((ent) => (
            <button
              key={ent.id}
              onClick={() => setSelectedEntity(ent)}
              className={`w-full text-left px-4 py-2 text-sm border-b border-gray-800/50 transition-colors ${
                selectedEntity?.id === ent.id
                  ? "bg-gray-800 text-white"
                  : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: getColor(ent.entity_type) }}
                />
                <span className="truncate" title={ent.name}>
                  {ent.name}
                </span>
              </div>
              <span className="text-[10px] text-gray-600 pl-4">
                {ent.entity_type}
                {ent.external_id && ent.external_id !== ent.id
                  ? ` · ${ent.external_id}`
                  : ""}
              </span>
            </button>
          ))}
          {filteredEntities.length > 200 && (
            <div className="px-4 py-2 text-xs text-gray-600">
              +{filteredEntities.length - 200} more…
            </div>
          )}
        </div>
      </div>

      {/* Canvas area */}
      <div className="flex-1 relative bg-gray-950">
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
        <div className="absolute top-4 right-4 flex flex-col gap-1">
          <button
            onClick={() => setZoom((z) => Math.min(4, z * 1.3))}
            className="p-2 rounded-lg bg-gray-800 border border-gray-700 text-gray-300 hover:text-white hover:bg-gray-700"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            onClick={() => setZoom((z) => Math.max(0.15, z / 1.3))}
            className="p-2 rounded-lg bg-gray-800 border border-gray-700 text-gray-300 hover:text-white hover:bg-gray-700"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <button
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}
            className="p-2 rounded-lg bg-gray-800 border border-gray-700 text-gray-300 hover:text-white hover:bg-gray-700"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
        </div>

        {/* Selection detail panel */}
        {selectedEntity && (
          <div className="absolute bottom-4 left-4 right-4 max-w-md bg-gray-900 border border-gray-700 rounded-xl p-4 shadow-2xl">
            <div className="flex items-center gap-3 mb-2">
              <span
                className="w-4 h-4 rounded-full flex-shrink-0"
                style={{
                  backgroundColor: getColor(selectedEntity.entity_type),
                }}
              />
              <h3 className="text-white font-bold text-lg">
                {selectedEntity.name}
              </h3>
              <span
                className={`ml-auto px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                  selectedEntity.status === "active"
                    ? "bg-green-900 text-green-300"
                    : selectedEntity.status === "critical"
                      ? "bg-red-900 text-red-300"
                      : "bg-gray-800 text-gray-400"
                }`}
              >
                {selectedEntity.status}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <span className="text-gray-500">Type</span>
              <span className="text-gray-200">
                {selectedEntity.entity_type}
              </span>
              {selectedEntity.external_id &&
                selectedEntity.external_id !== selectedEntity.id && (
                  <>
                    <span className="text-gray-500">External ID</span>
                    <span className="text-gray-200 font-mono text-xs">
                      {selectedEntity.external_id}
                    </span>
                  </>
                )}
              {selectedEntity.vendor && (
                <>
                  <span className="text-gray-500">Vendor</span>
                  <span className="text-gray-200">{selectedEntity.vendor}</span>
                </>
              )}
              {selectedEntity.zone && (
                <>
                  <span className="text-gray-500">Zone</span>
                  <span className="text-gray-200">{selectedEntity.zone}</span>
                </>
              )}
              <span className="text-gray-500">Connections</span>
              <span className="text-gray-200">
                {
                  relationships.filter(
                    (r) =>
                      r.source_entity_id === selectedEntity.id ||
                      r.target_entity_id === selectedEntity.id,
                  ).length
                }
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
