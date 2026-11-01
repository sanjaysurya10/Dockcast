import type { ModelSummary, Station } from "@/api/client";

import { STALE_AFTER_MS } from "./config";

export type StationState = "empty" | "full" | "ok" | "closed" | "unknown";

/** Current state from the latest observed status (the "Now" colouring of PRD 16.3). */
export function stationState(station: Pick<Station, "now" | "is_active">): StationState {
  const now = station.now;
  if (!now) return "unknown";
  if (!station.is_active || now.is_renting === false) return "closed";
  if (now.bikes === 0) return "empty";
  if (now.docks === 0) return "full";
  return "ok";
}

export const STATE_LABEL: Record<StationState, string> = {
  empty: "Empty",
  full: "Full",
  ok: "Bikes and docks",
  closed: "Closed",
  unknown: "No data",
};

/** True when the last collector run is missing or older than 5 min (PRD 16.3 item 10). */
export function isStale(lastRun: string | null | undefined, nowMs: number = Date.now()): boolean {
  if (!lastRun) return true;
  const age = nowMs - new Date(lastRun).getTime();
  return Number.isNaN(age) || age > STALE_AFTER_MS;
}

export interface ChampionRow {
  modelVersion: string;
  horizonMin: number;
  mae: number | null;
  mase: number | null;
  coverage80: number | null;
  runId: string | null;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * One row per champion horizon, sorted by horizon. `metrics` is the backtest written by the
 * forecast job: `{mae, mase, coverage_80, e1_run_id, model_name}`.
 */
export function championRows(summary: ModelSummary): ChampionRow[] {
  return summary.champions
    .filter((champion) => champion.horizon_min !== null)
    .map((champion) => {
      const metrics = champion.metrics;
      return {
        modelVersion: champion.model_version,
        horizonMin: champion.horizon_min ?? 0,
        mae: numberOrNull(metrics.mae),
        mase: numberOrNull(metrics.mase),
        coverage80: numberOrNull(metrics.coverage_80),
        runId: typeof metrics.e1_run_id === "string" ? metrics.e1_run_id : null,
      };
    })
    .sort((a, b) => a.horizonMin - b.horizonMin);
}

const TIME = new Intl.DateTimeFormat("en-IE", {
  timeZone: "Europe/Dublin",
  hour: "2-digit",
  minute: "2-digit",
});

const DAY = new Intl.DateTimeFormat("en-IE", {
  timeZone: "Europe/Dublin",
  day: "numeric",
  month: "short",
});

/** `hh:mm` in Dublin time (storage is UTC; display is Europe/Dublin). */
export function dublinTime(iso: string): string {
  return TIME.format(new Date(iso));
}

/** `hh:mm`, or `d Mon, hh:mm` when the time is not on today's Dublin date. */
export function dublinTimeOrDate(iso: string, nowMs: number = Date.now()): string {
  const when = new Date(iso);
  const sameDay = DAY.format(when) === DAY.format(new Date(nowMs));
  return sameDay ? TIME.format(when) : `${DAY.format(when)}, ${TIME.format(when)}`;
}
