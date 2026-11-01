import type { StationForecast, StationHistory } from "@/api/client";

export interface ChartPoint {
  t: number;
  actual?: number;
  p50?: number;
  band?: [number, number];
}

/**
 * Last hours of actual bikes joined to the forecast fan (PRD 16.4). The fan starts at the count
 * the model saw at issue time (the last 15-min state at or before it), so the band opens from
 * a single point on the actual line; the live count is the fallback when history is missing.
 */
export function forecastChartData(
  history: StationHistory | undefined,
  forecast: StationForecast,
): ChartPoint[] {
  const points: ChartPoint[] = (history?.points ?? [])
    .filter((point) => point.bikes !== null)
    .map((point) => ({ t: Date.parse(point.ts), actual: point.bikes ?? undefined }));
  const start = Date.parse(forecast.issued_at);
  const seen = points.filter((point) => point.t <= start).at(-1)?.actual;
  const anchor = seen ?? forecast.now?.bikes;
  if (anchor !== undefined) {
    const existing = points.find((point) => point.t === start);
    if (existing) {
      existing.p50 = anchor;
      existing.band = [anchor, anchor];
    } else {
      points.push({ t: start, p50: anchor, band: [anchor, anchor] });
    }
  }
  for (const row of forecast.forecasts) {
    points.push({
      t: Date.parse(row.target_ts),
      p50: row.bikes_p50,
      band: [row.bikes_p10, row.bikes_p90],
    });
  }
  return points.sort((a, b) => a.t - b.t);
}
