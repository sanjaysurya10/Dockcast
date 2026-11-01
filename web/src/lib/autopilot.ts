import type { RiskStation } from "@/api/client";

export const AUTOPILOT_STOPS = 10;
export const AUTOPILOT_FLY_MS = 2000;
export const AUTOPILOT_HOLD_MS = 4000;
export const AUTOPILOT_ZOOM = 16;
export const AUTOPILOT_PITCH = 45;

const LEVEL_RANK = { likely: 0, possible: 1, low: 2 } as const;

/**
 * The tour (PRD 16.3 item 7): the top at-risk stations, empty or full. "Likely" before
 * "possible"; ties keep the API's order (empty ranking). Low-risk stations are never toured.
 */
export function autopilotStops(
  rows: RiskStation[],
  limit: number = AUTOPILOT_STOPS,
): RiskStation[] {
  return rows
    .map((row, index) => ({
      row,
      index,
      rank: Math.min(LEVEL_RANK[row.empty_level], LEVEL_RANK[row.full_level]),
    }))
    .filter((item) => item.rank < LEVEL_RANK.low)
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .slice(0, limit)
    .map((item) => item.row);
}

/** Inputs that hand control back to the user. */
export const USER_INPUTS = ["pointerdown", "wheel", "keydown", "touchstart"] as const;
