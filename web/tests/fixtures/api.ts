import type {
  Backtest,
  City,
  CityNetFlow,
  CityRisk,
  ErrorAnalysis,
  Health,
  ModelSummary,
  RiskStation,
  Station,
  StationAlternatives,
  StationDrivers,
  StationForecast,
  StationHistory,
} from "@/api/client";

import errorAnalysisJson from "../../../reports/error_analysis.json" with { type: "json" };

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

/** Lyon (M20, live only): ROUVILLE from the Vélo'v feed on 2026-11-05; the key is illustrative. */
export const LYON_STATIONS: Station[] = [
  station(9001, "ROUVILLE", 17, 45.769684, 4.824607, 6, 10),
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
  // Hosted DB at 2026-11-01 13:35 UTC: 10,082 ok polls in 7 days (VM + fallback overlap).
  data_health: {
    collector_polls_7d: 10082,
    expected_polls_7d: 10080,
    collector_uptime_7d: 1,
    stations_modelled: 114,
    train_end: "2026-07-01T00:00:00Z",
  },
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
    forecasts: true,
    attribution: "Dublin City Council / Smart Dublin",
    source_url: "https://data.smartdublin.ie/",
    licence_name: "CC BY 4.0",
    licence_url: "https://creativecommons.org/licenses/by/4.0/",
  },
  {
    city_code: "lyon",
    name: "Lyon",
    timezone: "Europe/Paris",
    centre_lat: 45.7578,
    centre_lon: 4.832,
    default_zoom: 12.5,
    forecasts: false,
    attribution: "JCDecaux (Vélo'v)",
    source_url: "https://developer.jcdecaux.com/",
    licence_name: "Licence Ouverte (Etalab)",
    licence_url: "https://developer.jcdecaux.com/files/Open-Licence-fr.pdf",
  },
];

/** Hosted `station_status_15m` for station 5, 06:30-12:15 UTC on 2026-11-01: [hh:mm, bikes]. */
const HISTORY_5_BIKES: [string, number][] = [
  ["06:30", 0], ["06:45", 0], ["07:00", 0], ["07:15", 0], ["07:30", 0], ["07:45", 0],
  ["08:00", 0], ["08:15", 0], ["08:30", 0], ["08:45", 0], ["09:00", 0], ["09:15", 1],
  ["09:30", 0], ["09:45", 2], ["10:00", 2], ["10:15", 1], ["10:30", 1], ["10:45", 4],
  ["11:00", 4], ["11:15", 21], ["11:30", 23], ["11:45", 23], ["12:00", 24], ["12:15", 17],
]; // prettier-ignore

export const HISTORY_5: StationHistory = {
  station_key: 5,
  hours: 6,
  points: HISTORY_5_BIKES.map(([time, bikes]) => ({
    ts: `2026-11-01T${time}:00Z`,
    bikes,
    docks: 40 - bikes,
    is_imputed: false,
  })),
};

/**
 * Hosted `station_status_15m`, 11:15 -> 12:15 UTC on 2026-11-01. Station 5 jumped 4 -> 21 at
 * 11:15 and is rebalance-flagged inside the window, so it is excluded.
 */
export const NET_FLOW: CityNetFlow = {
  city: "dublin",
  window_min: 60,
  ts: "2026-11-01T12:15:00Z",
  stations: [
    { station_key: 5, net_flow: null, excluded: "rebalance" },
    { station_key: 14, net_flow: 3, excluded: null },
    { station_key: 15, net_flow: 0, excluded: null },
    { station_key: 33, net_flow: -3, excluded: null },
    { station_key: 68, net_flow: 1, excluded: null },
  ],
};

function haversineM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(a));
}

/** `GET /alternatives` from the real forecasts with the server's rule (P50 >= 3, 2 nearest). */
export function alternativesResponse(stationKey: number, horizon: number): StationAlternatives {
  const origin = STATIONS.find((s) => s.station_key === stationKey);
  const rows = STATIONS.filter((s) => s.station_key !== stationKey && origin)
    .map((s) => {
      const [, p10, p50, p90] = FORECASTS[s.station_key]?.find(([h]) => h === horizon) ?? [0, 0, 0, 0];
      const distance = haversineM(origin?.lat ?? 0, origin?.lon ?? 0, s.lat, s.lon);
      return {
        station_key: s.station_key,
        name: s.name,
        lat: s.lat,
        lon: s.lon,
        distance_m: Math.round(distance * 10) / 10,
        walk_m: Math.round(distance * 1.3 * 10) / 10,
        bikes_p10: p10,
        bikes_p50: p50,
        bikes_p90: p90,
      };
    })
    .filter((row) => row.bikes_p50 >= 3)
    .sort((a, b) => a.distance_m - b.distance_m)
    .slice(0, 2);
  return {
    station_key: stationKey,
    horizon_min: horizon,
    issued_at: "2026-11-01T12:15:00Z",
    alternatives: rows,
  };
}

/**
 * ILLUSTRATIVE driver values (no real TreeSHAP output exists yet: the hosted forecast job has
 * not been redeployed with M15). Test-only; never shown as real data.
 */
export const DRIVERS_5: StationDrivers = {
  station_key: 5,
  horizon_min: 60,
  issued_at: "2026-11-01T12:15:00Z",
  drivers: [
    { feature_group: "lags", contribution: 6.2 },
    { feature_group: "station", contribution: -2.4 },
    { feature_group: "calendar", contribution: 1.1 },
    { feature_group: "rolling", contribution: -0.6 },
    { feature_group: "seasonal", contribution: 0.3 },
    { feature_group: "station_static", contribution: 0.1 },
  ],
};

const E1_BACKTEST_RUN = "e4819616d7034b90abcb3adc882313da";

/** Local `backtest_results` of E1 run e4819616, overall, mean over 8 folds (2026-11-01). */
const E1_OVERALL: [string, number, number, number, number, number, number | null, number | null][] = [
  ["lgbm_global", 30, 604621, 0.9947, 1.9885, 0.9335, 0.8246, 3.0984],
  ["persistence", 30, 604621, 1.0659, 2.2184, 1.0, null, null],
  ["ridge", 30, 604621, 1.1795, 2.1346, 1.1076, null, null],
  ["seasonal_naive_7d", 30, 604621, 6.3545, 8.6892, 5.9928, null, null],
  ["lgbm_global", 60, 602561, 1.4608, 2.6875, 0.849, 0.814, 4.5949],
  ["persistence", 60, 602561, 1.7213, 3.3258, 1.0, null, null],
  ["ridge", 60, 602561, 1.8689, 3.104, 1.0869, null, null],
  ["seasonal_naive_7d", 60, 602561, 6.354, 8.6881, 3.7083, null, null],
  ["lgbm_global", 120, 598447, 2.0469, 3.4462, 0.74, 0.7972, 6.4353],
  ["persistence", 120, 598447, 2.7681, 4.9888, 1.0, null, null],
  ["ridge", 120, 598447, 2.874, 4.3435, 1.0399, null, null],
  ["seasonal_naive_7d", 120, 598447, 6.354, 8.6877, 2.3061, null, null],
];

/** Same run, `lgbm_global` at +60 by local hour: [coverage, mae]. */
const E1_HOUR_60: [number, number][] = [
  [0.7877, 0.8922], [0.8598, 0.3822], [0.9103, 0.032], [0.8989, 0.013], [0.8935, 0.0083],
  [0.7612, 0.2478], [0.7848, 1.2773], [0.7849, 1.8323], [0.7565, 2.446], [0.7916, 2.559],
  [0.8198, 2.056], [0.8145, 1.8083], [0.8122, 1.8591], [0.7934, 2.1494], [0.8169, 1.9223],
  [0.8182, 1.8245], [0.7928, 2.082], [0.7937, 2.2948], [0.7765, 2.1974], [0.8024, 1.8794],
  [0.806, 1.5627], [0.8187, 1.3026], [0.8104, 1.1862], [0.8308, 1.1224],
]; // prettier-ignore

export function backtestResponse(sliceKind: string): Backtest {
  const rows =
    sliceKind === "hour"
      ? E1_HOUR_60.map(([coverage, mae], hour) => ({
          model_name: "lgbm_global",
          horizon_min: 60,
          slice_value: String(hour),
          folds: 8,
          n: 0,
          mae,
          rmse: null,
          mase: null,
          coverage_80: coverage,
          interval_width: null,
        }))
      : E1_OVERALL.map(([model_name, horizon_min, n, mae, rmse, mase, coverage_80, interval_width]) => ({
          model_name,
          horizon_min,
          slice_value: "all",
          folds: 8,
          n,
          mae,
          rmse,
          mase,
          coverage_80,
          interval_width,
        }));
  return { experiment: "E1", run_id: E1_BACKTEST_RUN, slice_kind: sliceKind, rows };
}

/** The real `reports/error_analysis.json` (E1 e4819616 + E2 470f7279). */
export const ERROR_ANALYSIS = errorAnalysisJson as ErrorAnalysis;

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
  if (path === "/v1/cities/lyon/stations") return { status: 200, body: LYON_STATIONS };
  if (path === "/v1/cities/dublin/netflow") return { status: 200, body: NET_FLOW };
  if (path === "/v1/stations/5/forecast") return { status: 200, body: FORECAST_5 };
  if (path === "/v1/model/summary") return { status: 200, body: MODEL_SUMMARY };
  if (path === "/v1/stations/5/history") return { status: 200, body: HISTORY_5 };
  if (path === "/v1/stations/5/drivers") return { status: 200, body: DRIVERS_5 };
  const alternatives = /^\/v1\/stations\/(\d+)\/alternatives$/.exec(path);
  if (alternatives) {
    const horizon = Number(parsed.searchParams.get("horizon") ?? 30);
    return { status: 200, body: alternativesResponse(Number(alternatives[1]), horizon) };
  }
  if (path === "/v1/model/backtest") {
    const experiment = parsed.searchParams.get("experiment") ?? "E1";
    if (experiment !== "E1") {
      return {
        status: 404,
        body: { error: { code: "backtest_not_found", message: `no backtest rows for ${experiment}` } },
      };
    }
    return { status: 200, body: backtestResponse(parsed.searchParams.get("slice_kind") ?? "overall") };
  }
  if (path === "/v1/model/error-analysis") return { status: 200, body: ERROR_ANALYSIS };
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
