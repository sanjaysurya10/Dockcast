import { useMemo } from "react";

import type { ErrorAnalysis } from "@/api/client";
import { mix } from "@/lib/backtest";
import { tokenRgb } from "@/lib/tokens";
import { useDarkMode } from "@/lib/useMediaQuery";

const CELL_W = 20;
const CELL_H = 5;

/** Station x hour MAE at +60, worst stations at the top (PRD 13.4 question 2, 16.5). */
export function ErrorHeatmap({ analysis }: { analysis: ErrorAnalysis }) {
  const dark = useDarkMode();
  // Token values change with the colour scheme, so `dark` is the cache key.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ramp = useMemo(() => [tokenRgb("--brand-tint"), tokenRgb("--brand-ink")] as const, [dark]);
  const values = analysis.heatmap.flatMap((row) => row.mae.filter((v): v is number => v !== null));
  const maximum = Math.max(...values, 1e-9);
  const hours = analysis.heatmap_hours;
  const width = hours.length * CELL_W;
  const height = analysis.heatmap.length * CELL_H;
  const run = `MLflow run ${analysis.run_id}`;
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm text-muted">
        MAE at +60 min for each station (rows, worst at the top) by local hour of the target.
        Stronger colour means larger errors (scale below); hover a cell for its value. {run}.
      </figcaption>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width + 32} ${height + 20}`}
          className="w-full max-w-2xl"
          role="img"
          aria-label={`Heatmap of error by station and hour; ${analysis.heatmap.length} stations`}
        >
          <g transform="translate(32, 0)">
            {analysis.heatmap.map((row, r) =>
              row.mae.map((value, h) => (
                <rect
                  key={`${row.station_key}-${h}`}
                  x={h * CELL_W}
                  y={r * CELL_H}
                  width={CELL_W - 1}
                  height={CELL_H - 0.5}
                  fill={value === null ? "var(--ground)" : mix(ramp[0], ramp[1], value / maximum)}
                >
                  <title>
                    {`${row.name}, ${String(hours[h] ?? h).padStart(2, "0")}:00 — MAE ${
                      value === null ? "no data" : value.toFixed(2)
                    } bikes (${run})`}
                  </title>
                </rect>
              )),
            )}
            {hours
              .filter((hour) => hour % 3 === 0)
              .map((hour) => (
                <text
                  key={hour}
                  x={hour * CELL_W + CELL_W / 2}
                  y={height + 14}
                  textAnchor="middle"
                  fontSize={10}
                  fill="var(--muted)"
                >
                  {String(hour).padStart(2, "0")}
                </text>
              ))}
          </g>
        </svg>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted" aria-hidden="true">
        <span className="num">0</span>
        <span
          className="h-2 w-32 rounded-full"
          style={{ background: "linear-gradient(to right, var(--brand-tint), var(--brand-ink))" }}
        />
        <span className="num">{maximum.toFixed(1)} bikes</span>
      </div>
    </figure>
  );
}
