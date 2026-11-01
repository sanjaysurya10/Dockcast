import type { RiskStation, Station } from "@/api/client";

import { stationState } from "./status";

export type Horizon = "now" | 30 | 60 | 120;
export const HORIZON_OPTIONS: Horizon[] = ["now", 30, 60, 120];

/** What a station marker shows: current state ("now") or interim forecast-range risk. */
export type MapState =
  | "empty"
  | "empty-possible"
  | "full"
  | "full-possible"
  | "ok"
  | "closed"
  | "unknown";

export const MAP_STATE_LABEL: Record<MapState, string> = {
  empty: "Empty",
  "empty-possible": "May empty",
  full: "Full",
  "full-possible": "May fill",
  ok: "Bikes and docks",
  closed: "Closed",
  unknown: "No data",
};

/** Forecast labels say "likely" because they are a forecast, not an observation. */
export const FORECAST_LABEL: Partial<Record<MapState, string>> = {
  empty: "Likely empty",
  full: "Likely full",
};

export function stateLabel(state: MapState, horizon: Horizon): string {
  return (horizon !== "now" && FORECAST_LABEL[state]) || MAP_STATE_LABEL[state];
}

/** Colour of a state as design-token names: fill, outline (PRD 16.2; never red/green). */
export const MAP_STATE_TOKENS: Record<MapState, { fill: string; line: string }> = {
  empty: { fill: "--risk-empty", line: "--surface" },
  "empty-possible": { fill: "--risk-empty-tint", line: "--risk-empty" },
  full: { fill: "--risk-full", line: "--surface" },
  "full-possible": { fill: "--risk-full-tint", line: "--risk-full" },
  ok: { fill: "--risk-ok", line: "--surface" },
  closed: { fill: "--line", line: "--muted" },
  unknown: { fill: "--line", line: "--muted" },
};

/** Interim forecast state: a "likely" level wins over "possible"; empty wins a tie. */
export function forecastState(risk: RiskStation): MapState {
  if (risk.empty_level === "likely") return "empty";
  if (risk.full_level === "likely") return "full";
  if (risk.empty_level === "possible") return "empty-possible";
  if (risk.full_level === "possible") return "full-possible";
  return "ok";
}

export interface MapStation {
  stationKey: number;
  name: string;
  lat: number;
  lon: number;
  capacity: number;
  state: MapState;
}

/**
 * Stations with the state to draw at `horizon`. "Now" uses the latest status; a forecast
 * horizon uses the risk rows, and a station without a forecast row shows "No data".
 */
export function mapStations(
  stations: Station[],
  horizon: Horizon,
  risk: RiskStation[] | undefined,
): MapStation[] {
  const byKey = new Map((risk ?? []).map((row) => [row.station_key, row]));
  return stations.map((station) => {
    let state: MapState;
    if (horizon === "now" || !risk) {
      state = stationState(station);
    } else {
      const row = byKey.get(station.station_key);
      state = row ? forecastState(row) : "unknown";
    }
    return {
      stationKey: station.station_key,
      name: station.name,
      lat: station.lat,
      lon: station.lon,
      capacity: station.capacity,
      state,
    };
  });
}

/** Marker radius in metres, growing with capacity (PRD 16.3 item 3). */
export function capacityRadius(capacity: number): number {
  return 14 + Math.sqrt(Math.max(capacity, 0)) * 4;
}

export function etaLabel(minutes: number | null | undefined, kind: "empty" | "full"): string {
  if (minutes === null || minutes === undefined) return "";
  return `${kind === "empty" ? "Empty" : "Full"} by +${minutes} min`;
}

export function horizonLabel(horizon: Horizon): string {
  return horizon === "now" ? "Now" : `+${horizon}`;
}
