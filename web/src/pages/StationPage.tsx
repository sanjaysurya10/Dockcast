import { Link, useParams } from "react-router";

import { ApiError, type HorizonForecast } from "@/api/client";
import { useStationForecast } from "@/api/queries";
import { ErrorMessage, Loading } from "@/components/QueryState";
import { dublinTime } from "@/lib/status";

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
        Back to all stations
      </Link>
    </div>
  );
}

export function StationPage() {
  const stationKey = Number(useParams().stationKey);
  const forecast = useStationForecast(stationKey);

  if (!Number.isInteger(stationKey) || stationKey <= 0) return <NotFoundStation />;
  if (forecast.isPending) return <Loading label="the forecast" />;
  if (forecast.isError) {
    const code = forecast.error instanceof ApiError ? forecast.error.code : null;
    if (code === "station_not_found") return <NotFoundStation />;
    if (code === "forecast_not_found") {
      return (
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">No forecast yet</h1>
          <p className="text-muted">
            This station has no forecast, for example because it is new since the last training.
          </p>
          <Link to="/" className="text-brand-ink underline">
            Back to all stations
          </Link>
        </div>
      );
    }
    return <ErrorMessage error={forecast.error} label="the forecast" />;
  }
  const data = forecast.data;
  return (
    <article className="space-y-6">
      <header>
        <Link to="/" className="text-sm text-brand-ink underline">
          All stations
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">{data.name}</h1>
        <p className="text-sm text-muted">
          {data.capacity} docks · forecast issued {dublinTime(data.issued_at)} · model{" "}
          <span className="num">{data.model_version}</span>
        </p>
      </header>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Bikes now" value={data.now ? String(data.now.bikes) : "–"} />
        <Tile label="Docks now" value={data.now ? String(data.now.docks) : "–"} />
        {data.forecasts.map((item) => (
          <ForecastTile key={item.horizon_min} forecast={item} />
        ))}
      </div>
      {data.data_freshness.stale && (
        <p role="status" className="text-sm text-risk-empty-ink">
          This forecast is based on delayed data.
        </p>
      )}
    </article>
  );
}
