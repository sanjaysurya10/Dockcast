import type {
  City,
  CityRisk,
  Health,
  ModelSummary,
  RiskStation,
  Station,
  StationForecast,
} from "@/api/client";

/**
 * Real-shaped API responses for tests. Station rows and statuses are the hosted database's
 * 2026-11-01 12:24 UTC poll; the forecast is the 12:15 UTC issue for station 5. The status and
 * forecast ages in `data_freshness` are illustrative.
 */
const OBSERVED_AT = "2026-11-01T12:24:00Z";

function station(
  station_key: number,
  name: string,
  capacity: number,
  lat: number,
  lon: number,
  bikes: number,
  docks: number,
): Station {
  return {
    station_key,
    name,
    lat,
    lon,
    capacity,
    is_active: true,
    now: { bikes, docks, observed_at: OBSERVED_AT, is_renting: true },
    risk: null,
  };
}

export const STATIONS: Station[] = [
  station(5, "CHARLEMONT PLACE", 40, 53.330704, -6.260004, 18, 22),
  station(14, "FOWNES STREET UPPER", 30, 53.344603, -6.263371, 30, 0),
  station(15, "HARDWICKE STREET", 16, 53.355473, -6.264423, 0, 16),
  station(33, "PRINCES STREET / O'CONNELL STREET", 23, 53.349013, -6.260311, 15, 8),
  station(68, "GRAND CANAL DOCK", 40, 53.342638, -6.238695, 33, 7),
];

export const FORECAST_5: StationForecast = {
  station_key: 5,
  name: "CHARLEMONT PLACE",
  capacity: 40,
  issued_at: "2026-11-01T12:15:00Z",
  model_version: "lgbm-q-2026-06-30-3c421b6",
  now: { bikes: 18, docks: 22, observed_at: OBSERVED_AT, is_renting: true },
  forecasts: [
    {
      horizon_min: 30,
      target_ts: "2026-11-01T12:45:00Z",
      bikes_p10: 19.0729,
      bikes_p50: 22.7684,
      bikes_p90: 25.6747,
    },
    {
      horizon_min: 60,
      target_ts: "2026-11-01T13:15:00Z",
      bikes_p10: 17.1462,
      bikes_p50: 21.9349,
      bikes_p90: 26.8233,
    },
    {
      horizon_min: 120,
      target_ts: "2026-11-01T14:15:00Z",
      bikes_p10: 12.9375,
      bikes_p50: 20.0105,
      bikes_p90: 26.8173,
    },
  ],
  risk: null,
  data_freshness: { status_age_s: 51, forecast_age_s: 540, stale: false },
};

const E1_RUN = "fb0d738826974ae9982cc4e96b96e5ba";

function champion(horizon: number, mae: number, mase: number, coverage: number) {
  return {
    model_version: `lgbm-q-2026-06-30-3c421b6-h${horizon}`,
    horizon_min: horizon,
    trained_at: "2026-10-27T01:09:11.935612Z",
    train_end: "2026-07-01T00:00:00Z",
    metrics: { mae, mase, coverage_80: coverage, e1_run_id: E1_RUN, model_name: "lgbm_global" },
  };
}

/** The hosted `model_versions` champions (one row per horizon), queried 2026-11-01. */
export const MODEL_SUMMARY: ModelSummary = {
  champions: [
    champion(120, 2.046859984478931, 0.7400458884188439, 0.7971937050023408),
    champion(30, 0.9947425276727324, 0.9334559685123723, 0.8246291935498582),
    champion(60, 1.460765689208001, 0.8490414066701389, 0.8139580496384038),
  ],
  last_retrain: "2026-10-27T01:09:11.935612Z",
};

export function health(lastCollectorRun: string | null): Health {
  return {
    status: "ok",
    db: "ok",
    last_collector_run: lastCollectorRun,
    last_forecast_issued_at: "2026-11-01T12:15:00Z",
  };
}

/** Hosted-DB forecasts of the 2026-11-01 12:15 UTC issue: [horizon, p10, p50, p90]. */
const FORECASTS: Record<number, [number, number, number, number][]> = {
  5: [[30, 19.073, 22.768, 25.675], [60, 17.146, 21.935, 26.823], [120, 12.938, 20.011, 26.817]],
  14: [[30, 23.488, 28.817, 30], [60, 20.015, 29.603, 30], [120, 16.879, 28.536, 30]],
  15: [[30, 0, 0, 1.045], [60, 0, 0.055, 1.482], [120, 0, 0.2, 1.976]],
  33: [[30, 12.663, 16.098, 19.585], [60, 10.693, 17.995, 22.577], [120, 8.137, 19.575, 22.151]],
  68: [[30, 29.596, 33.02, 36.139], [60, 28.123, 33.166, 37.419], [120, 22.395, 30.283, 37.881]],
};

type Level = "likely" | "possible" | "low";
const NEAR_ZERO = 0.5; // dockcast/api/risk.py

function level(likely: number, possible: number): Level {
  if (likely <= NEAR_ZERO) return "likely";
  return possible <= NEAR_ZERO ? "possible" : "low";
}

function eta(rows: [number, number, number, number][], free: (p50: number) => number) {
  return rows.find(([, , p50]) => free(p50) <= NEAR_ZERO)?.[0] ?? null;
}

/** `GET /v1/cities/dublin/risk` built from the real forecasts with the server's rules. */
export function riskResponse(window: number, kind: "empty" | "full", limit: number): CityRisk {
  const rank: Record<Level, number> = { likely: 0, possible: 1, low: 2 };
  const rows: RiskStation[] = STATIONS.map((s) => {
    const all = FORECASTS[s.station_key] ?? [];
    const [, p10, p50, p90] = all.find(([h]) => h === window) ?? [window, 0, 0, 0];
    return {
      station_key: s.station_key,
      name: s.name,
      lat: s.lat,
      lon: s.lon,
      capacity: s.capacity,
      now: s.now,
      horizon_min: window,
      bikes_p10: p10,
      bikes_p50: p50,
      bikes_p90: p90,
      empty_level: level(p50, p10),
      full_level: level(s.capacity - p50, s.capacity - p90),
      eta_empty_min: eta(all, (b) => b),
      eta_full_min: eta(all, (b) => s.capacity - b),
    };
  });
  const free = (r: RiskStation) => (kind === "empty" ? r.bikes_p50 : r.capacity - r.bikes_p50);
  rows.sort(
    (a, b) =>
      rank[kind === "empty" ? a.empty_level : a.full_level] -
        rank[kind === "empty" ? b.empty_level : b.full_level] || free(a) - free(b),
  );
  return {
    city: "dublin",
    window_min: window,
    kind,
    basis: "forecast_range",
    issued_at: "2026-11-01T12:15:00Z",
    model_version: `lgbm-q-2026-06-30-3c421b6-h${window}`,
    total: rows.length,
    stations: rows.slice(0, limit),
  };
}

export const CITIES: City[] = [
  {
    city_code: "dublin",
    name: "Dublin",
    timezone: "Europe/Dublin",
    centre_lat: 53.3473,
    centre_lon: -6.2591,
    default_zoom: 13,
  },
];

/** Route table shared by the unit and e2e mocks. */
export function mockResponse(url: string, now: Date = new Date()): { status: number; body: unknown } {
  const parsed = new URL(url);
  const path = parsed.pathname;
  if (path === "/health") return { status: 200, body: health(now.toISOString()) };
  if (path === "/v1/cities") return { status: 200, body: CITIES };
  if (path === "/v1/cities/dublin/risk") {
    const query = parsed.searchParams;
    const kind = query.get("kind") === "full" ? "full" : "empty";
    const body = riskResponse(Number(query.get("window") ?? 60), kind, Number(query.get("limit") ?? 20));
    return { status: 200, body };
  }
  if (path === "/v1/cities/dublin/stations") return { status: 200, body: STATIONS };
  if (path === "/v1/stations/5/forecast") return { status: 200, body: FORECAST_5 };
  if (path === "/v1/model/summary") return { status: 200, body: MODEL_SUMMARY };
  if (path === "/v1/stations/15/forecast") {
    return {
      status: 404,
      body: { error: { code: "forecast_not_found", message: "no forecast for station 15" } },
    };
  }
  return {
    status: 404,
    body: { error: { code: "station_not_found", message: `no route ${path}` } },
  };
}
