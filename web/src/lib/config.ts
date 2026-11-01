const DEFAULT_API_BASE = "http://127.0.0.1:8000";

export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? DEFAULT_API_BASE).replace(
  /\/$/,
  "",
);

export const CITY = "dublin";
export const HORIZONS = [30, 60, 120] as const;
export const STALE_AFTER_MS = 5 * 60 * 1000;
