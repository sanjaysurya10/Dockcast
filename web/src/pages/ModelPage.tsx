import { useState } from "react";

import { useBacktest, useErrorAnalysis, useModelSummary } from "@/api/queries";
import { CoverageChart } from "@/components/model/CoverageChart";
import { ErrorHeatmap } from "@/components/model/ErrorHeatmap";
import { FoldDiagram } from "@/components/model/FoldDiagram";
import { HorizonChart } from "@/components/model/HorizonChart";
import { ResultsTable } from "@/components/model/ResultsTable";
import { ErrorMessage, Loading } from "@/components/QueryState";
import { WhenVisible } from "@/components/WhenVisible";
import { championRows } from "@/lib/status";

const EXPERIMENTS = [
  { id: "E1", label: "E1 · models vs baselines" },
  { id: "E2", label: "E2 · global vs per-station vs per-cluster" },
  { id: "E4", label: "E4 · spatial features" },
  { id: "E7", label: "E7 · feature ablation (+60, oracle weather)" },
];

const DATE = new Intl.DateTimeFormat("en-IE", {
  timeZone: "Europe/Dublin",
  day: "numeric",
  month: "short",
  year: "numeric",
});

function fixed(value: number | null, digits: number): string {
  return value === null ? "–" : value.toFixed(digits);
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function HealthTile({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="rounded-card border border-line bg-surface p-4" title={title}>
      <p className="text-sm text-muted">{label}</p>
      <p className="num text-xl font-semibold">{value}</p>
    </div>
  );
}

/** Model performance (PRD 16.5). Every number names its MLflow run (on hover or in captions). */
export function ModelPage() {
  const summary = useModelSummary();
  const [experiment, setExperiment] = useState("E1");
  const backtest = useBacktest(experiment, "overall");
  const hourly = useBacktest("E1", "hour");
  const analysis = useErrorAnalysis();

  return (
    <div className="space-y-10">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Model accuracy</h1>
        <p className="text-sm text-muted">
          Every number comes from a rolling-origin backtest on weeks the model had not seen. MAE
          and RMSE are in bikes; MASE below 1 beats “no change”; coverage is how often the actual
          count fell inside P10–P90 (target 0.80). Hover a value for its MLflow run.
        </p>
      </header>

      <Section id="served-heading" title="Served model">
        {summary.isPending && <Loading label="model metrics" />}
        {summary.isError && <ErrorMessage error={summary.error} label="model metrics" />}
        {summary.data && (
          <div className="overflow-x-auto rounded-card border border-line bg-surface">
            <table className="w-full text-sm">
              <caption className="sr-only">Backtest metrics of the served model per horizon</caption>
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
      </Section>

      <Section id="results-heading" title="Backtest results">
        <label className="flex flex-wrap items-center gap-2 text-sm">
          Experiment
          <select
            value={experiment}
            onChange={(event) => setExperiment(event.target.value)}
            className="min-h-11 rounded-control border border-line bg-surface px-2"
          >
            {EXPERIMENTS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {backtest.isPending && (
          <div className="min-h-[36rem]">
            <Loading label="backtest results" />
          </div>
        )}
        {backtest.isError && (
          <p className="text-sm text-muted">
            No backtest results for {experiment} are published in this database yet.
          </p>
        )}
        {backtest.data && (
          <>
            <p className="text-xs text-muted">
              Mean over folds. Best value per column per horizon is highlighted. MLflow run{" "}
              <span className="num">{backtest.data.run_id}</span>.
            </p>
            <ResultsTable backtest={backtest.data} />
          </>
        )}
      </Section>

      <Section id="folds-heading" title="How the backtest works">
        {analysis.data ? (
          <FoldDiagram folds={analysis.data.folds} />
        ) : (
          analysis.isError && <p className="text-sm text-muted">Fold dates are not published yet.</p>
        )}
      </Section>

      <Section id="errors-heading" title="Where the model is wrong">
        {analysis.isPending && <Loading label="error analysis" />}
        {analysis.isError && (
          <p className="text-sm text-muted">The error analysis is not published yet.</p>
        )}
        {analysis.data && (
          <WhenVisible minHeight={640}>
            <div className="grid gap-8 lg:grid-cols-2">
              <ErrorHeatmap analysis={analysis.data} />
              <HorizonChart analysis={analysis.data} />
            </div>
          </WhenVisible>
        )}
      </Section>

      <Section id="calibration-heading" title="Calibration">
        {hourly.data ? (
          <WhenVisible minHeight={320}>
            <CoverageChart backtest={hourly.data} />
          </WhenVisible>
        ) : (
          hourly.isError && <p className="text-sm text-muted">Coverage by hour is not published yet.</p>
        )}
        <p className="text-sm text-muted">
          Calibration of empty/full probabilities arrives with the event models (M10); the map's
          risk levels currently come from the forecast range.
        </p>
      </Section>

      <Section id="health-heading" title="Data health">
        {summary.data && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <HealthTile
              label="Collector uptime, 7 days"
              value={`${(summary.data.data_health.collector_uptime_7d * 100).toFixed(1)} %`}
              title={`${summary.data.data_health.collector_polls_7d} of ${summary.data.data_health.expected_polls_7d} expected polls`}
            />
            <HealthTile
              label="Stations modelled"
              value={String(summary.data.data_health.stations_modelled)}
            />
            <HealthTile
              label="Trained on data up to"
              value={
                summary.data.data_health.train_end
                  ? DATE.format(Date.parse(summary.data.data_health.train_end))
                  : "–"
              }
            />
            <HealthTile
              label="Last retrain"
              value={summary.data.last_retrain ? DATE.format(Date.parse(summary.data.last_retrain)) : "–"}
            />
          </div>
        )}
      </Section>
    </div>
  );
}
