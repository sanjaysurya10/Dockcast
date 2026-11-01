import type { StationDrivers } from "@/api/client";

/** Plain-language names for the model's feature groups (PRD 16.4 "What drives this forecast"). */
export const DRIVER_LABEL: Record<string, string> = {
  lags: "Bikes there now and in the last 2 hours",
  rolling: "Trend over the last few hours",
  seasonal: "Same time yesterday and last week",
  calendar: "Time of day and day of the week",
  station_static: "Station size and location",
  station: "This station's usual pattern",
  other: "Other factors",
};

export interface DriverChip {
  group: string;
  label: string;
  bikes: number;
  direction: "up" | "down";
}

/** The `count` largest drivers (the API sorts by absolute contribution). */
export function topDrivers(drivers: StationDrivers, count = 4): DriverChip[] {
  return drivers.drivers.slice(0, count).map((driver) => ({
    group: driver.feature_group,
    label: DRIVER_LABEL[driver.feature_group] ?? driver.feature_group,
    bikes: driver.contribution,
    direction: driver.contribution >= 0 ? "up" : "down",
  }));
}

/** Haversine distance x 1.3, rounded to 50 m (PRD 16.4, labelled approximate). */
export function walkLabel(walkM: number): string {
  if (walkM < 1000) return `approx. ${Math.max(50, Math.round(walkM / 50) * 50)} m walk`;
  return `approx. ${(walkM / 1000).toFixed(1)} km walk`;
}
