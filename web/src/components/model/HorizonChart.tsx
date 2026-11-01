import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ErrorAnalysis } from "@/api/client";
import { modelLabel } from "@/lib/backtest";
import { useReducedMotion } from "@/lib/useMediaQuery";

/** Series styling: the two LightGBM variants get categorical colours, baselines stay muted. */
const SERIES: Record<string, { stroke: string; dash?: string }> = {
  lgbm_global: { stroke: "var(--series-1)" },
  lgbm_per_cluster: { stroke: "var(--series-2)" },
  persistence: { stroke: "var(--muted)", dash: "6 4" },
  ridge: { stroke: "var(--muted)", dash: "2 3" },
};

/** MAE growth from +30 to +120 (PRD 13.4 question 4). */
export function HorizonChart({ analysis }: { analysis: ErrorAnalysis }) {
  const reducedMotion = useReducedMotion();
  const models = [...new Set(analysis.horizon_growth.map((row) => row.model_name))];
  const horizons = [...new Set(analysis.horizon_growth.map((row) => row.horizon_min))].sort(
    (a, b) => a - b,
  );
  // The global model is drawn last so it stays on top where the two LightGBM lines overlap.
  const drawOrder = [...models].sort((a, b) => Number(a === "lgbm_global") - Number(b === "lgbm_global"));
  const data = horizons.map((horizon) => ({
    horizon,
    ...Object.fromEntries(
      analysis.horizon_growth
        .filter((row) => row.horizon_min === horizon)
        .map((row) => [row.model_name, row.mae]),
    ),
  }));
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm text-muted">
        MAE (bikes) over every test row as the horizon grows; the two LightGBM lines nearly
        overlap. MLflow runs {analysis.run_id}
        {analysis.e2_run_id ? ` and ${analysis.e2_run_id}` : ""}.
      </figcaption>
      <div className="h-64 rounded-card border border-line bg-surface p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: -8 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis
              dataKey="horizon"
              tickFormatter={(value: number) => `+${value}`}
              stroke="var(--muted)"
              fontSize={12}
            />
            <YAxis stroke="var(--muted)" fontSize={12} width={40} />
            <Tooltip
              formatter={(value, name) => [Number(value).toFixed(3), modelLabel(String(name))]}
              labelFormatter={(label) => `+${String(label)} min`}
            />
            {drawOrder.map((model) => (
              <Line
                key={model}
                dataKey={model}
                name={model}
                stroke={SERIES[model]?.stroke ?? "var(--muted)"}
                strokeDasharray={SERIES[model]?.dash}
                strokeWidth={2}
                dot={{ r: 4, fill: "var(--surface)" }}
                isAnimationActive={!reducedMotion}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Legend">
        {models.map((model) => (
          <li key={model} className="flex items-center gap-2">
            <svg width="24" height="8" aria-hidden="true">
              <line
                x1="0"
                x2="24"
                y1="4"
                y2="4"
                stroke={SERIES[model]?.stroke ?? "var(--muted)"}
                strokeWidth="2"
                strokeDasharray={SERIES[model]?.dash}
              />
            </svg>
            {modelLabel(model)}
          </li>
        ))}
      </ul>
    </figure>
  );
}
