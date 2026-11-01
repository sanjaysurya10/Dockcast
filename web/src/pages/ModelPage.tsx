import { useModelSummary } from "@/api/queries";
import { ErrorMessage, Loading } from "@/components/QueryState";
import { championRows } from "@/lib/status";

function fixed(value: number | null, digits: number): string {
  return value === null ? "–" : value.toFixed(digits);
}

export function ModelPage() {
  const summary = useModelSummary();
  return (
    <section aria-labelledby="model-heading" className="space-y-4">
      <h1 id="model-heading" className="text-2xl font-semibold">
        Model accuracy
      </h1>
      <p className="text-sm text-muted">
        Backtest metrics of the served model. MAE is in bikes; MASE below 1 beats “no change”;
        coverage is how often the actual count fell inside P10–P90 (target 0.80). Hover a row for
        its MLflow run.
      </p>
      {summary.isPending && <Loading label="model metrics" />}
      {summary.isError && <ErrorMessage error={summary.error} label="model metrics" />}
      {summary.data && (
        <div className="overflow-x-auto rounded-card border border-line bg-surface">
          <table className="w-full text-sm">
            <caption className="sr-only">Backtest metrics per horizon</caption>
            <thead className="text-left text-muted">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">
                  Horizon
                </th>
                <th scope="col" className="px-4 py-2 text-right font-medium">
                  MAE
                </th>
                <th scope="col" className="px-4 py-2 text-right font-medium">
                  MASE
                </th>
                <th scope="col" className="px-4 py-2 text-right font-medium">
                  Coverage
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Model
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {championRows(summary.data).map((row) => (
                <tr
                  key={`${row.modelVersion}-${row.horizonMin}`}
                  title={row.runId ? `MLflow run ${row.runId}` : undefined}
                >
                  <th scope="row" className="px-4 py-2 text-left font-medium">
                    +{row.horizonMin} min
                  </th>
                  <td className="num px-4 py-2 text-right">{fixed(row.mae, 3)}</td>
                  <td className="num px-4 py-2 text-right">{fixed(row.mase, 3)}</td>
                  <td className="num px-4 py-2 text-right">{fixed(row.coverage80, 3)}</td>
                  <td className="num px-4 py-2 text-muted">{row.modelVersion}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
