import type { BacktestRow } from "@/api/client";

export type Metric = "mae" | "rmse" | "mase" | "coverage_80" | "interval_width";
export const METRICS: Metric[] = ["mae", "rmse", "mase", "coverage_80", "interval_width"];
const COVERAGE_TARGET = 0.8;

export const MODEL_LABEL: Record<string, string> = {
  lgbm_global: "LightGBM (global)",
  lgbm_per_cluster: "LightGBM (per cluster)",
  lgbm_per_station: "LightGBM (per station)",
  persistence: "Persistence (no change)",
  seasonal_naive_7d: "Same time last week",
  ridge: "Ridge regression",
  prophet_station: "Prophet",
};

export function modelLabel(name: string): string {
  return MODEL_LABEL[name] ?? name;
}

/**
 * The best model per metric within one horizon: lowest error and width, coverage closest to
 * 0.80. Ties all count as best.
 */
export function bestByMetric(rows: BacktestRow[]): Record<Metric, Set<string>> {
  const best = {} as Record<Metric, Set<string>>;
  for (const metric of METRICS) {
    const score = (row: BacktestRow): number | null => {
      const value = row[metric];
      if (value === null || Number.isNaN(value)) return null;
      return metric === "coverage_80" ? Math.abs(value - COVERAGE_TARGET) : value;
    };
    const scored = rows.flatMap((row) => {
      const value = score(row);
      return value === null ? [] : [{ model: row.model_name, value }];
    });
    const minimum = Math.min(...scored.map((item) => item.value));
    best[metric] = new Set(
      scored.filter((item) => Math.abs(item.value - minimum) < 1e-9).map((item) => item.model),
    );
  }
  return best;
}

/** Rows grouped by horizon, best model first by MAE. */
export function byHorizon(rows: BacktestRow[]): Map<number, BacktestRow[]> {
  const groups = new Map<number, BacktestRow[]>();
  for (const row of rows) groups.set(row.horizon_min, [...(groups.get(row.horizon_min) ?? []), row]);
  for (const group of groups.values()) group.sort((a, b) => (a.mae ?? Infinity) - (b.mae ?? Infinity));
  return new Map([...groups].sort(([a], [b]) => a - b));
}

/** Linear interpolation between two RGB colours (for the single-hue heatmap ramp). */
export function mix(low: [number, number, number], high: [number, number, number], t: number) {
  const clamped = Math.min(1, Math.max(0, t));
  const channel = (i: 0 | 1 | 2) => Math.round(low[i] + (high[i] - low[i]) * clamped);
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`;
}
