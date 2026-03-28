"use client";

/**
 * TopologyMapView — Leaflet-based geographic overlay for topology nodes.
 *
 * Renders nodes with geo coordinates as device-icon markers on a CartoDB
 * tile layer, with polyline edges between connected nodes.
 * Icons match the 11 categories used in the force-directed canvas view.
 *
 * Lazy-loaded via next/dynamic (SSR disabled) from topology/page.tsx.
 */

import React, { useMemo, useEffect, useRef } from "react";
import { useTheme } from "@/app/context/ThemeContext";
import { MapContainer, TileLayer, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import "leaflet/dist/leaflet.css";

/* ── Props (mirror the parent page's data) ───────────────────── */
interface Entity {
  id: string;
  name: string;
  entity_type: string;
  status: string;
  external_id?: string;
  geo_lat?: number | null;
  geo_lon?: number | null;
}

interface Relationship {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
}

interface Props {
  entities: Entity[];
  relationships: Relationship[];
  shadowEntities: Entity[];
  shadowRelationships: Relationship[];
  seedId: string | null;
  selectedEntity: Entity | null;
  onSelectEntity: (e: Entity) => void;
  getColor: (entityType: string) => string;
  hiddenTypes: Set<string>;
  showInferred: boolean;
}

/* ── Status colors (kept in sync with the canvas view) ───────── */
const STATUS_COLORS: Record<string, string> = {
  critical: "#ef4444",
  degraded: "#f59e0b",
  down: "#ef4444",
  active: "#22c55e",
  operational: "#22c55e",
  in_service: "#22c55e",
  maintenance: "#f59e0b",
  unknown: "#64748b",
};

/* ── Icon shape mapping (mirrors topology/page.tsx) ──────────── */
type IconShape = "tower" | "router" | "switch" | "server" | "cloud" | "antenna" | "optical" | "firewall" | "database" | "link" | "default";

const TYPE_ICON: Record<string, IconShape> = {
  site: "tower", gnodeb: "tower", enodeb: "tower", bsc: "tower", rnc: "tower",
  cell: "antenna", sector: "antenna",
  router: "router", core_router: "router",
  switch: "switch", aggregation_switch: "switch",
  olt: "optical", onu: "optical",
  mme: "cloud", sgw: "cloud", pgw: "cloud", msc: "cloud", hlr: "cloud",
  pcrf: "cloud", upf: "cloud", smf: "cloud", amf: "cloud", nrf: "cloud",
  microwave_link: "link", fiber_link: "link", transmission: "link",
  server: "server", web_server: "server", dns_server: "server", mail_server: "server",
  workstation: "server",
  firewall: "firewall",
  ids: "firewall",
  database: "database",
  emergency_service: "server",
};

function getIconShape(entityType: string): IconShape {
  const key = entityType.toLowerCase().replace(/[\s-]/g, "_");
  return TYPE_ICON[key] ?? "default";
}

/** SVG path content for each icon shape (drawn inside a 24x24 viewBox) */
function svgIconPath(shape: IconShape, color: string): string {
  const s = `stroke="${color}" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"`;
  const sf = `stroke="${color}" fill="${color}" stroke-width="0"`;

  switch (shape) {
    case "tower":
      return `<path d="M12 3 L7 21 M12 3 L17 21 M9 12 L15 12 M8 17 L16 17" ${s}/>
              <circle cx="12" cy="2" r="1.5" ${sf}/>
              <path d="M8.5 1 A4.5 4.5 0 0 1 12 0" ${s} fill="none" stroke-width="1"/>
              <path d="M15.5 1 A4.5 4.5 0 0 0 12 0" ${s} fill="none" stroke-width="1"/>`;
    case "antenna":
      return `<line x1="12" y1="20" x2="12" y2="8" ${s}/>
              <polygon points="12,4 9,10 15,10" ${sf}/>
              <line x1="8" y1="20" x2="16" y2="20" ${s}/>
              <path d="M7 3 A6 6 0 0 1 12 1" ${s} fill="none" stroke-width="1"/>
              <path d="M17 3 A6 6 0 0 0 12 1" ${s} fill="none" stroke-width="1"/>`;
    case "router":
      return `<ellipse cx="12" cy="8" rx="8" ry="3" ${s}/>
              <path d="M4 8 L4 16" ${s}/><path d="M20 8 L20 16" ${s}/>
              <ellipse cx="12" cy="16" rx="8" ry="3" ${s}/>
              <line x1="8" y1="12" x2="16" y2="12" ${s}/>
              <polyline points="14.5,10.5 16,12 14.5,13.5" ${s}/>
              <polyline points="9.5,10.5 8,12 9.5,13.5" ${s}/>`;
    case "switch":
      return `<rect x="3" y="7" width="18" height="10" rx="2" ${s}/>
              <circle cx="7" cy="14" r="1.2" ${sf}/>
              <circle cx="10.5" cy="14" r="1.2" ${sf}/>
              <circle cx="14" cy="14" r="1.2" ${sf}/>
              <circle cx="17.5" cy="14" r="1.2" ${sf}/>`;
    case "server":
      return `<rect x="5" y="3" width="14" height="7" rx="1.5" ${s}/>
              <rect x="5" y="13" width="14" height="7" rx="1.5" ${s}/>
              <circle cx="16" cy="6.5" r="1" ${sf}/>
              <circle cx="16" cy="16.5" r="1" ${sf}/>`;
    case "cloud":
      return `<path d="M6 18 Q2 18 2 14 Q2 10 6 10 Q6 6 10 6 Q14 4 17 7 Q22 7 22 12 Q22 18 17 18 Z" ${s}/>`;
    case "optical":
      return `<polygon points="12,3 21,12 12,21 3,12" ${s}/>
              <line x1="8" y1="12" x2="16" y2="12" ${s} stroke-width="1"/>
              <line x1="12" y1="8" x2="12" y2="16" ${s} stroke-width="1"/>`;
    case "firewall":
      return `<rect x="3" y="4" width="18" height="16" rx="1" ${s}/>
              <line x1="3" y1="12" x2="21" y2="12" ${s}/>
              <line x1="12" y1="4" x2="12" y2="12" ${s}/>
              <line x1="7.5" y1="12" x2="7.5" y2="20" ${s}/>
              <line x1="16.5" y1="12" x2="16.5" y2="20" ${s}/>`;
    case "database":
      return `<ellipse cx="12" cy="6" rx="8" ry="3" ${s}/>
              <path d="M4 6 L4 18" ${s}/><path d="M20 6 L20 18" ${s}/>
              <ellipse cx="12" cy="18" rx="8" ry="3" ${s}/>
              <ellipse cx="12" cy="12" rx="8" ry="2.5" ${s} stroke-width="1"/>`;
    case "link":
      return `<polyline points="4,12 9,6 15,18 20,12" ${s}/>
              <circle cx="4" cy="12" r="2" ${sf}/>
              <circle cx="20" cy="12" r="2" ${sf}/>`;
    default: // hexagon
      return `<polygon points="12,2 20,7 20,17 12,22 4,17 4,7" ${s}/>`;
  }
}

/** Build a Leaflet DivIcon with the device SVG */
function buildDivIcon(
  shape: IconShape,
  fillColor: string,
  borderColor: string,
  isSeed: boolean,
  isSelected: boolean,
): L.DivIcon {
  const size = isSeed ? 36 : isSelected ? 30 : 24;
  const ring = isSeed ? 3 : isSelected ? 2 : 0;
  const ringColor = isSeed ? "#fbbf24" : borderColor;
  const outerSize = size + ring * 2 + 4;

  const html = `
    <div style="
      width:${outerSize}px; height:${outerSize}px;
      display:flex; align-items:center; justify-content:center;
      border-radius:50%;
      background: radial-gradient(circle, ${borderColor}33 0%, transparent 70%);
      ${ring > 0 ? `box-shadow: 0 0 0 ${ring}px ${ringColor};` : ""}
    ">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
           width="${size}" height="${size}" style="filter: drop-shadow(0 1px 2px rgba(0,0,0,0.5));">
        ${svgIconPath(shape, fillColor)}
      </svg>
    </div>`;

  return L.divIcon({
    html,
    className: "",  // suppress default leaflet-div-icon styling
    iconSize: [outerSize, outerSize],
    iconAnchor: [outerSize / 2, outerSize / 2],
    tooltipAnchor: [0, -(outerSize / 2)],
  });
}

/* ── Helper: auto-fit bounds when data changes ───────────────── */
function FitBounds({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap();
  const fitted = useRef(false);

  useEffect(() => {
    if (bounds && !fitted.current) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
      fitted.current = true;
    }
  }, [bounds, map]);

  useEffect(() => {
    fitted.current = false;
  }, [bounds]);

  return null;
}

/* ── Map tile URLs (CartoDB — theme-aware) ────────────────────── */
const TILE_URLS = {
  dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  light: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
};
const TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>';

export default function TopologyMapView({
  entities,
  relationships,
  shadowEntities,
  shadowRelationships,
  seedId,
  selectedEntity,
  onSelectEntity,
  getColor,
  hiddenTypes,
  showInferred,
}: Props) {
  const { theme } = useTheme();
  const isLight = theme === "light";

  /* Apply hiddenTypes filter, then split into geo-located vs unmapped */
  const { geoEntities, unmappedCount, visibleNodeIds, entMap, bounds } = useMemo(() => {
    const visible = entities.filter((e) => !hiddenTypes.has(e.entity_type));
    const geo: Entity[] = [];
    const map = new Map<string, Entity>();
    const nodeIds = new Set<string>();
    let unmapped = 0;

    visible.forEach((e) => {
      map.set(e.id, e);
      nodeIds.add(e.id);
      if (e.geo_lat != null && e.geo_lon != null) {
        geo.push(e);
      } else {
        unmapped++;
      }
    });

    let b: [[number, number], [number, number]] | null = null;
    if (geo.length > 0) {
      let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
      geo.forEach((e) => {
        const lat = e.geo_lat!;
        const lon = e.geo_lon!;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
        if (lon < minLon) minLon = lon;
        if (lon > maxLon) maxLon = lon;
      });
      const latPad = maxLat === minLat ? 0.01 : 0;
      const lonPad = maxLon === minLon ? 0.01 : 0;
      b = [
        [minLat - latPad, minLon - lonPad],
        [maxLat + latPad, maxLon + lonPad],
      ];
    }

    return { geoEntities: geo, unmappedCount: unmapped, visibleNodeIds: nodeIds, entMap: map, bounds: b };
  }, [entities, hiddenTypes]);

  /* Edges between visible geo-located nodes */
  const geoEdges = useMemo(() => {
    return relationships
      .filter((rel) => visibleNodeIds.has(rel.source_entity_id) && visibleNodeIds.has(rel.target_entity_id))
      .map((rel) => {
        const src = entMap.get(rel.source_entity_id);
        const tgt = entMap.get(rel.target_entity_id);
        if (
          src?.geo_lat != null && src?.geo_lon != null &&
          tgt?.geo_lat != null && tgt?.geo_lon != null
        ) {
          return {
            id: rel.id,
            positions: [
              [src.geo_lat, src.geo_lon] as [number, number],
              [tgt.geo_lat, tgt.geo_lon] as [number, number],
            ],
          };
        }
        return null;
      })
      .filter(Boolean) as { id: string; positions: [number, number][] }[];
  }, [relationships, visibleNodeIds, entMap]);

  /* Shadow (inferred) edges between visible geo-located nodes */
  const geoShadowEdges = useMemo(() => {
    if (!showInferred) return [];
    return shadowRelationships
      .map((rel) => {
        // Shadow edges can reference either regular or shadow entities
        const src = entMap.get(rel.source_entity_id);
        const tgt = entMap.get(rel.target_entity_id);
        if (
          src?.geo_lat != null && src?.geo_lon != null &&
          tgt?.geo_lat != null && tgt?.geo_lon != null
        ) {
          return {
            id: rel.id,
            positions: [
              [src.geo_lat, src.geo_lon] as [number, number],
              [tgt.geo_lat, tgt.geo_lon] as [number, number],
            ],
          };
        }
        return null;
      })
      .filter(Boolean) as { id: string; positions: [number, number][] }[];
  }, [shadowRelationships, showInferred, entMap]);

  const defaultCenter: [number, number] = geoEntities.length > 0
    ? [geoEntities[0].geo_lat!, geoEntities[0].geo_lon!]
    : [20, 0];

  if (geoEntities.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center justify-center flex-col text-white/70">
        <p className="text-lg">No geographic coordinates available</p>
        <p className="text-sm mt-1 text-white/50">
          {entities.length} nodes in view have no lat/lon data.
          Switch to Graph view to explore the topology.
        </p>
      </div>
    );
  }

  return (
    <div className="absolute inset-0">
      <MapContainer
        center={defaultCenter}
        zoom={6}
        className="w-full h-full"
        style={{ background: isLight ? "#f0f4f8" : "#020d18" }}
        zoomControl={false}
        attributionControl={true}
      >
        <TileLayer key={theme} url={isLight ? TILE_URLS.light : TILE_URLS.dark} attribution={TILE_ATTR} />
        <FitBounds bounds={bounds} />

        {/* Shadow (inferred) edges — dashed purple */}
        {geoShadowEdges.map((edge) => (
          <Polyline
            key={`shadow-${edge.id}`}
            positions={edge.positions}
            pathOptions={{
              color: isLight ? "rgba(139, 92, 246, 0.4)" : "rgba(139, 92, 246, 0.55)",
              weight: 1.5,
              dashArray: "6 4",
            }}
          />
        ))}

        {/* Edges as polylines */}
        {geoEdges.map((edge) => (
          <Polyline
            key={edge.id}
            positions={edge.positions}
            pathOptions={{
              color: isLight ? "rgba(15, 23, 42, 0.25)" : "rgba(0, 212, 255, 0.35)",
              weight: 1.5,
            }}
          />
        ))}

        {/* Nodes as device-icon markers */}
        {geoEntities.map((ent) => {
          const isSeed = ent.id === seedId;
          const isSelected = selectedEntity?.id === ent.id;
          const fillColor = getColor(ent.entity_type);
          const borderColor = STATUS_COLORS[ent.status] ?? STATUS_COLORS.unknown;
          const shape = getIconShape(ent.entity_type);
          const icon = buildDivIcon(shape, fillColor, borderColor, isSeed, isSelected);

          return (
            <Marker
              key={ent.id}
              position={[ent.geo_lat!, ent.geo_lon!]}
              icon={icon}
              eventHandlers={{
                click: () => onSelectEntity(ent),
              }}
            >
              <Tooltip
                direction="top"
                offset={[0, -4]}
                className="topology-map-tooltip"
              >
                <div style={{ fontSize: 11, lineHeight: 1.4 }}>
                  <strong>{ent.name}</strong>
                  <br />
                  <span style={{ opacity: 0.7 }}>{ent.entity_type}</span>
                  {isSeed && <span style={{ color: "#fbbf24", marginLeft: 4 }}>SEED</span>}
                </div>
              </Tooltip>
            </Marker>
          );
        })}
      </MapContainer>

      {/* Unmapped node count badge */}
      {unmappedCount > 0 && (
        <div className="absolute bottom-4 right-4 px-3 py-1.5 rounded-lg bg-[#0a2d4a] border border-cyan-900/40 text-white/70 text-xs z-[1000] shadow-lg">
          {unmappedCount} node{unmappedCount > 1 ? "s" : ""} without coordinates (graph-only)
        </div>
      )}
    </div>
  );
}
