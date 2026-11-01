import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { StationForecast, StationHistory } from "@/api/client";
import { type ChartPoint, forecastChartData } from "@/lib/chartData";
import { dublinTime } from "@/lib/status";
import { useReducedMotion } from "@/lib/useMediaQuery";

const time = (ms: number) => dublinTime(new Date(ms).toISOString());

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: ChartPoint }[] }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="rounded-control border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="font-medium">{time(point.t)}</p>
      {point.actual !== undefined && <p className="num">Actual: {point.actual} bikes</p>}
      {point.p50 !== undefined && point.band && point.band[0] !== point.band[1] && (
        <p className="num">
          Forecast: {point.p50.toFixed(1)} (likely {Math.round(point.band[0])}–
          {Math.round(point.band[1])})
        </p>
      )}
    </div>
  );
}

/** Last 6 h actual + next 2 h forecast with the P10-P90 band (PRD 16.4). */
export function ForecastChart({
  forecast,
  history,
}: {
  forecast: StationForecast;
  history: StationHistory | undefined;
}) {
  const reducedMotion = useReducedMotion();
  const data = forecastChartData(history, forecast);
  const now = Date.parse(forecast.issued_at);
  const forecastRows = forecast.forecasts;
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm text-muted">
        Bikes over the last 6 hours (solid) and the forecast for the next 2 hours (dashed, with the
        likely P10–P90 range shaded). The orange strip marks empty.
      </figcaption>
      <div className="h-72 w-full rounded-card border border-line bg-surface p-2">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={time}
              stroke="var(--muted)"
              fontSize={12}
            />
            <YAxis
              domain={[0, forecast.capacity]}
              allowDecimals={false}
              stroke="var(--muted)"
              fontSize={12}
              width={40}
            />
            <ReferenceArea y1={0} y2={0.5} fill="var(--risk-empty-tint)" fillOpacity={1} />
            <Area
              dataKey="band"
              stroke="none"
              fill="var(--brand-tint)"
              fillOpacity={1}
              isAnimationActive={!reducedMotion}
              connectNulls
            />
            <Line
              dataKey="actual"
              stroke="var(--ink)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={!reducedMotion}
              connectNulls
            />
            <Line
              dataKey="p50"
              stroke="var(--brand)"
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={{ r: 3, fill: "var(--brand)" }}
              isAnimationActive={!reducedMotion}
              connectNulls
            />
            <ReferenceLine
              x={now}
              stroke="var(--muted)"
              strokeDasharray="3 3"
              label={{ value: "Now", position: "insideTopLeft", fill: "var(--muted)", fontSize: 12 }}
            />
            <Tooltip content={<ChartTooltip />} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted">Show forecast as a table</summary>
        <table className="mt-2 w-full">
          <thead className="text-left text-muted">
            <tr>
              <th scope="col" className="py-1 font-medium">
                Time
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Bikes (median)
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Likely range
              </th>
            </tr>
          </thead>
          <tbody>
            {forecastRows.map((row) => (
              <tr key={row.horizon_min}>
                <th scope="row" className="num py-1 text-left font-normal">
                  +{row.horizon_min} min ({dublinTime(row.target_ts)})
                </th>
                <td className="num py-1 text-right">{row.bikes_p50.toFixed(1)}</td>
                <td className="num py-1 text-right">
                  {Math.round(row.bikes_p10)}–{Math.round(row.bikes_p90)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
