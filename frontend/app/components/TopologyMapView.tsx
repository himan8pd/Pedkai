"use client";

/**
 * TopologyMapView — Leaflet-based geographic overlay for topology nodes.
 *
 * Renders nodes with geo coordinates as circle markers on an OpenStreetMap
 * tile layer, with polyline edges between connected nodes.
 * Nodes without coordinates are listed in a small "unmapped" badge.
 *
 * Lazy-loaded via next/dynamic (SSR disabled) from topology/page.tsx.
 */

import React, { useMemo, useEffect, useRef } from "react";
import { MapContainer, TileLayer, CircleMarker, Polyline, Tooltip, useMap } from "react-leaflet";
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
  seedId: string | null;
  selectedEntity: Entity | null;
  onSelectEntity: (e: Entity) => void;
  getColor: (entityType: string) => string;
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

  // Reset when bounds reference changes (new seed)
  useEffect(() => {
    fitted.current = false;
  }, [bounds]);

  return null;
}

/* ── Dark-themed map tile URL (CartoDB dark_all) ─────────────── */
const DARK_TILE_URL =
  "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
const DARK_TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>';

export default function TopologyMapView({
  entities,
  relationships,
  seedId,
  selectedEntity,
  onSelectEntity,
  getColor,
}: Props) {
  /* Split entities into geo-located vs unmapped */
  const { geoEntities, unmappedCount, entMap, bounds } = useMemo(() => {
    const geo: Entity[] = [];
    const map = new Map<string, Entity>();
    let unmapped = 0;

    entities.forEach((e) => {
      map.set(e.id, e);
      if (e.geo_lat != null && e.geo_lon != null) {
        geo.push(e);
      } else {
        unmapped++;
      }
    });

    // Compute bounds from geo entities
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
      // Add small padding for single-point case
      const latPad = maxLat === minLat ? 0.01 : 0;
      const lonPad = maxLon === minLon ? 0.01 : 0;
      b = [
        [minLat - latPad, minLon - lonPad],
        [maxLat + latPad, maxLon + lonPad],
      ];
    }

    return { geoEntities: geo, unmappedCount: unmapped, entMap: map, bounds: b };
  }, [entities]);

  /* Edges between geo-located nodes */
  const geoEdges = useMemo(() => {
    return relationships
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
  }, [relationships, entMap]);

  /* Default center (world center if no geo data) */
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
        style={{ background: "#020d18" }}
        zoomControl={false}
        attributionControl={true}
      >
        <TileLayer url={DARK_TILE_URL} attribution={DARK_TILE_ATTR} />
        <FitBounds bounds={bounds} />

        {/* Edges as polylines */}
        {geoEdges.map((edge) => (
          <Polyline
            key={edge.id}
            positions={edge.positions}
            pathOptions={{
              color: "rgba(0, 212, 255, 0.35)",
              weight: 1.5,
              dashArray: undefined,
            }}
          />
        ))}

        {/* Nodes as circle markers */}
        {geoEntities.map((ent) => {
          const isSeed = ent.id === seedId;
          const isSelected = selectedEntity?.id === ent.id;
          const fillColor = getColor(ent.entity_type);
          const borderColor = STATUS_COLORS[ent.status] ?? STATUS_COLORS.unknown;
          const radius = isSeed ? 10 : isSelected ? 8 : 6;

          return (
            <CircleMarker
              key={ent.id}
              center={[ent.geo_lat!, ent.geo_lon!]}
              radius={radius}
              pathOptions={{
                fillColor,
                fillOpacity: isSelected || isSeed ? 1 : 0.8,
                color: isSeed ? "#fbbf24" : borderColor,
                weight: isSeed ? 3 : isSelected ? 2.5 : 1.5,
                opacity: 1,
              }}
              eventHandlers={{
                click: () => onSelectEntity(ent),
              }}
            >
              <Tooltip
                direction="top"
                offset={[0, -8]}
                className="topology-map-tooltip"
              >
                <div style={{ fontSize: 11, lineHeight: 1.4 }}>
                  <strong>{ent.name}</strong>
                  <br />
                  <span style={{ opacity: 0.7 }}>{ent.entity_type}</span>
                  {isSeed && <span style={{ color: "#fbbf24", marginLeft: 4 }}>SEED</span>}
                </div>
              </Tooltip>
            </CircleMarker>
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
