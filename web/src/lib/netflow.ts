import type { CityNetFlow, Station } from "@/api/client";

export type FlowDirection = "inflow" | "outflow";

export interface NetFlowPoint {
  stationKey: number;
  name: string;
  lat: number;
  lon: number;
  net: number;
  direction: FlowDirection;
}

export interface NetFlowSummary {
  points: NetFlowPoint[];
  inflow: number;
  outflow: number;
  unchanged: number;
  excluded: number;
}

/**
 * Stations with a non-zero net change, joined to their positions (PRD 16.3 item 8). Stations
 * excluded by the API (rebalancing, closed, missing) and unchanged ones draw no ring.
 */
export function netFlowSummary(stations: Station[], flow: CityNetFlow | undefined): NetFlowSummary {
  const byKey = new Map(stations.map((station) => [station.station_key, station]));
  const summary: NetFlowSummary = {
    points: [],
    inflow: 0,
    outflow: 0,
    unchanged: 0,
    excluded: 0,
  };
  for (const row of flow?.stations ?? []) {
    const station = byKey.get(row.station_key);
    if (!station) continue;
    if (row.net_flow === null) {
      summary.excluded += 1;
      continue;
    }
    if (row.net_flow === 0) {
      summary.unchanged += 1;
      continue;
    }
    const direction: FlowDirection = row.net_flow > 0 ? "inflow" : "outflow";
    summary[direction] += 1;
    summary.points.push({
      stationKey: station.station_key,
      name: station.name,
      lat: station.lat,
      lon: station.lon,
      net: row.net_flow,
      direction,
    });
  }
  return summary;
}

const BASE_M = 30;
const PER_BIKE_M = 14;
const MAX_M = 220;

/** Ring radius in metres for a net change; grows with the square root of |net|. */
export function ringRadius(net: number): number {
  return Math.min(MAX_M, BASE_M + PER_BIKE_M * Math.sqrt(Math.abs(net)) * 2);
}

/**
 * Pulse at `phase` in [0, 1): inflow rings expand outward, outflow rings contract inward;
 * both fade as they travel. Returns the radius scale and opacity (0-255).
 */
export function pulse(direction: FlowDirection, phase: number): { scale: number; alpha: number } {
  const travel = direction === "inflow" ? phase : 1 - phase;
  return {
    scale: 0.6 + 0.8 * travel,
    alpha: Math.round(255 * (1 - phase) ** 0.8),
  };
}

export function netFlowLabel(net: number): string {
  const bikes = Math.abs(net) === 1 ? "bike" : "bikes";
  return net > 0 ? `+${net} ${bikes} (inflow)` : `${net} ${bikes} (outflow)`;
}
