import type { Backtest } from "@/api/client";
import { bestByMetric, byHorizon, type Metric, METRICS, modelLabel } from "@/lib/backtest";

const HEADERS: Record<Metric, string> = {
  mae: "MAE",
  rmse: "RMSE",
  mase: "MASE",
  coverage_80: "Coverage",
  interval_width: "Width",
};

function format(value: number | null, metric: Metric): string {
  if (value === null || Number.isNaN(value)) return "–";
  return metric === "interval_width" ? value.toFixed(2) : value.toFixed(3);
}

/** Backtest results per horizon with the best value per column highlighted (PRD 16.5). */
export function ResultsTable({ backtest }: { backtest: Backtest }) {
  const runTitle = `MLflow run ${backtest.run_id}`;
  return (
    <div className="space-y-6">
      {[...byHorizon(backtest.rows)].map(([horizon, rows]) => {
        const best = bestByMetric(rows);
        return (
          <div key={horizon} className="overflow-x-auto rounded-card border border-line bg-surface">
            <table className="w-full text-sm">
              <caption className="px-4 pt-3 text-left font-medium">+{horizon} min</caption>
              <thead className="text-left text-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">
                    Model
                  </th>
                  {METRICS.map((metric) => (
                    <th key={metric} scope="col" className="px-4 py-2 text-right font-medium">
                      {HEADERS[metric]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((row) => (
                  <tr key={row.model_name} title={runTitle}>
                    <th scope="row" className="px-4 py-2 text-left font-normal">
                      {modelLabel(row.model_name)}
                    </th>
                    {METRICS.map((metric) => {
                      const isBest = best[metric].has(row.model_name);
                      return (
                        <td
                          key={metric}
                          title={runTitle}
                          className={`num px-4 py-2 text-right ${
                            isBest ? "bg-brand-tint font-semibold text-brand-ink" : ""
                          }`}
                        >
                          {format(row[metric], metric)}
                          {isBest && <span className="sr-only"> (best)</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
