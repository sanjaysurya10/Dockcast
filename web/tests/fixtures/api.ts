import type { Health, ModelSummary, Station, StationForecast } from "@/api/client";

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

/** Route table shared by the unit and e2e mocks. */
export function mockResponse(url: string, now: Date = new Date()): { status: number; body: unknown } {
  const path = new URL(url).pathname;
  if (path === "/health") return { status: 200, body: health(now.toISOString()) };
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
