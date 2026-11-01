import { Link, useParams } from "react-router";

import { ApiError, type HorizonForecast } from "@/api/client";
import { useCityRisk, useStationForecast, useStationHistory } from "@/api/queries";
import { Alternatives } from "@/components/Alternatives";
import { DriverChips } from "@/components/DriverChips";
import { ForecastChart } from "@/components/ForecastChart";
import { ErrorMessage, Loading } from "@/components/QueryState";
import { forecastState, MAP_STATE_TOKENS, stateLabel } from "@/lib/risk";
import { dublinTime } from "@/lib/status";

const RISK_HORIZON = 60;
const HISTORY_HOURS = 6;

function Tile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="num text-2xl font-semibold">{value}</p>
      {detail && <p className="num text-xs text-muted">{detail}</p>}
    </div>
  );
}

function ForecastTile({ forecast }: { forecast: HorizonForecast }) {
  return (
    <Tile
      label={`Bikes at +${forecast.horizon_min} min (${dublinTime(forecast.target_ts)})`}
      value={forecast.bikes_p50.toFixed(1)}
      detail={`likely ${Math.round(forecast.bikes_p10)}–${Math.round(forecast.bikes_p90)} (P10–P90)`}
    />
  );
}

function NotFoundStation() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">Station not found</h1>
      <Link to="/" className="text-brand-ink underline">
        Back to the map
      </Link>
    </div>
  );
}

function NoForecast() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">No forecast yet</h1>
      <p className="text-muted">
        This station has no forecast, for example because it is new since the last training.
      </p>
      <Link to="/" className="text-brand-ink underline">
        Back to the map
      </Link>
    </div>
  );
}

/** Interim +60 risk badge from the forecast range (owner decision, PRD 23). */
function RiskBadge({ stationKey }: { stationKey: number }) {
  const risk = useCityRisk(RISK_HORIZON, "empty", 200);
  const row = risk.data?.stations.find((item) => item.station_key === stationKey);
  if (!row) return null;
  const state = forecastState(row);
  const tokens = MAP_STATE_TOKENS[state];
  return (
    <span
      className="inline-flex items-center gap-2 rounded-control border px-2 py-0.5 text-xs font-medium"
      style={{ borderColor: `var(${tokens.fill})` }}
      title="From the forecast range (P10–P90), not a probability"
    >
      <span
        aria-hidden="true"
        className="size-2.5 rounded-full"
        style={{ background: `var(${tokens.fill})` }}
      />
      {state === "ok" ? "Not at risk" : stateLabel(state, RISK_HORIZON)} at +{RISK_HORIZON}
    </span>
  );
}

export function StationPage() {
  const stationKey = Number(useParams().stationKey);
  const valid = Number.isInteger(stationKey) && stationKey > 0;
  const forecast = useStationForecast(stationKey);
  const history = useStationHistory(valid ? stationKey : 0, HISTORY_HOURS);

  if (!valid) return <NotFoundStation />;
  if (forecast.isPending) return <Loading label="the forecast" />;
  if (forecast.isError) {
    const code = forecast.error instanceof ApiError ? forecast.error.code : null;
    if (code === "station_not_found") return <NotFoundStation />;
    if (code === "forecast_not_found") return <NoForecast />;
    return <ErrorMessage error={forecast.error} label="the forecast" />;
  }
  const data = forecast.data;
  const byHorizon = new Map(data.forecasts.map((row) => [row.horizon_min, row]));
  const tiles = [60, 120].flatMap((horizon) => byHorizon.get(horizon) ?? []);
  return (
    <article className="space-y-8">
      <header className="space-y-2">
        <Link to="/" className="text-sm text-brand-ink underline">
          Back to the map
        </Link>
        <h1 className="text-2xl font-semibold">{data.name}</h1>
        <div className="flex flex-wrap items-center gap-3 text-sm text-muted">
          <span>{data.capacity} docks</span>
          <RiskBadge stationKey={stationKey} />
          <span>
            Forecast issued {dublinTime(data.issued_at)} · model{" "}
            <span className="num">{data.model_version}</span>
          </span>
        </div>
      </header>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Bikes now" value={data.now ? String(data.now.bikes) : "–"} />
        <Tile label="Docks now" value={data.now ? String(data.now.docks) : "–"} />
        {tiles.map((item) => (
          <ForecastTile key={item.horizon_min} forecast={item} />
        ))}
      </div>
      {data.data_freshness.stale && (
        <p role="status" className="text-sm text-risk-empty-ink">
          This forecast is based on delayed data.
        </p>
      )}
      <ForecastChart forecast={data} history={history.data} />
      <div className="grid gap-8 md:grid-cols-2">
        <Alternatives stationKey={stationKey} />
        <DriverChips stationKey={stationKey} />
      </div>
    </article>
  );
}
