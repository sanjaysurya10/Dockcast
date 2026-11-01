import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Backtest } from "@/api/client";
import { useReducedMotion } from "@/lib/useMediaQuery";

/** P10-P90 coverage of the served model at +60 by local hour (PRD 16.5, E6). */
export function CoverageChart({ backtest }: { backtest: Backtest }) {
  const reducedMotion = useReducedMotion();
  const data = backtest.rows
    .filter((row) => row.model_name === "lgbm_global" && row.horizon_min === 60)
    .map((row) => ({ hour: Number(row.slice_value), coverage: row.coverage_80 }))
    .sort((a, b) => a.hour - b.hour);
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm text-muted">
        How often the actual count fell inside the P10–P90 range at +60, by local hour (target
        0.80; the band is the accepted 0.70–0.90). MLflow run {backtest.run_id}.
      </figcaption>
      <div className="h-56 rounded-card border border-line bg-surface p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <ReferenceArea y1={0.7} y2={0.9} fill="var(--brand-tint)" fillOpacity={1} />
            <ReferenceLine y={0.8} stroke="var(--muted)" strokeDasharray="3 3" />
            <XAxis
              dataKey="hour"
              ticks={[0, 3, 6, 9, 12, 15, 18, 21]}
              tickFormatter={(hour: number) => `${String(hour).padStart(2, "0")}:00`}
              stroke="var(--muted)"
              fontSize={12}
            />
            <YAxis domain={[0.6, 1]} stroke="var(--muted)" fontSize={12} width={40} />
            <Tooltip
              formatter={(value) => [Number(value).toFixed(3), "Coverage"]}
              labelFormatter={(hour) => `${String(hour).padStart(2, "0")}:00`}
            />
            <Line
              dataKey="coverage"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={{ r: 3 }}
              isAnimationActive={!reducedMotion}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
