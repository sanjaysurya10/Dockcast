const DEFAULT_API_BASE = "http://127.0.0.1:8000";

export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? DEFAULT_API_BASE).replace(
  /\/$/,
  "",
);

export const CITY = "dublin";
export const HORIZONS = [30, 60, 120] as const;
export const STALE_AFTER_MS = 5 * 60 * 1000;

/** OpenFreeMap styles (free, no key; attribution comes with the style). PRD 23, M13. */
export const MAP_STYLE_LIGHT: string =
  import.meta.env.VITE_MAP_STYLE_LIGHT ?? "https://tiles.openfreemap.org/styles/positron";
export const MAP_STYLE_DARK: string =
  import.meta.env.VITE_MAP_STYLE_DARK ?? "https://tiles.openfreemap.org/styles/dark";

/** PRD 16.3 level of detail: stations from zoom 9, names from zoom 15. */
export const STATION_ZOOM = 9;
export const LABEL_ZOOM = 15;
