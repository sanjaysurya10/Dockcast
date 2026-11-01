import type { Station } from "@/api/client";

const EARTH_M = 6_371_000;
export const WALK_FACTOR = 1.3; // PRD 16.4: haversine x 1.3, labelled "approx."
export const NEARBY_COUNT = 5;

export interface Position {
  lat: number;
  lon: number;
}

export interface NearbyStation {
  station: Station;
  walkM: number;
}

export function haversineM(a: Position, b: Position): number {
  const rad = Math.PI / 180;
  const h =
    Math.sin(((b.lat - a.lat) * rad) / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(((b.lon - a.lon) * rad) / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.sqrt(h));
}

/** The nearest active stations to `here`, computed in the browser only (PRD 16.6). */
export function nearestStations(
  stations: Station[],
  here: Position,
  count: number = NEARBY_COUNT,
): NearbyStation[] {
  return stations
    .filter((station) => station.is_active)
    .map((station) => ({
      station,
      walkM: haversineM(here, station) * WALK_FACTOR,
    }))
    .sort((a, b) => a.walkM - b.walkM)
    .slice(0, count);
}
