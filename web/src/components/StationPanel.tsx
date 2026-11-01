import { Link } from "react-router";

import { ApiError, type Station } from "@/api/client";
import { useStationForecast } from "@/api/queries";
import { dublinTime, stationState } from "@/lib/status";

import { StateBadge } from "./StateBadge";

interface StationPanelProps {
  station: Station;
  onClose: () => void;
}

/** Side panel for the selected station: now and the three forecast horizons (PRD 16.3 item 5). */
export function StationPanel({ station, onClose }: StationPanelProps) {
  const forecast = useStationForecast(station.station_key);
  const noForecast = forecast.error instanceof ApiError;
  return (
    <section aria-labelledby="station-panel-heading" className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 id="station-panel-heading" className="text-lg font-semibold">
            {station.name}
          </h2>
          <p className="text-sm text-muted">{station.capacity} docks</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="min-h-11 rounded-control px-3 text-sm text-muted hover:text-ink"
        >
          Close
        </button>
      </div>
      <div className="flex items-center gap-3">
        <StateBadge state={stationState(station)} />
        {station.now && (
          <span className="num text-sm">
            {station.now.bikes} bikes · {station.now.docks} docks · {dublinTime(station.now.observed_at)}
          </span>
        )}
      </div>
      {forecast.isPending && (
        <p role="status" className="text-sm text-muted">
          Loading forecast…
        </p>
      )}
      {noForecast && <p className="text-sm text-muted">No forecast is available right now.</p>}
      {forecast.data && (
        <table className="w-full text-sm">
          <caption className="sr-only">Forecast bikes</caption>
          <thead className="text-left text-muted">
            <tr>
              <th scope="col" className="py-1 font-medium">
                When
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Bikes
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Likely range
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {forecast.data.forecasts.map((row) => (
              <tr key={row.horizon_min}>
                <th scope="row" className="num py-1 text-left font-normal">
                  +{row.horizon_min} ({dublinTime(row.target_ts)})
                </th>
                <td className="num py-1 text-right">{row.bikes_p50.toFixed(1)}</td>
                <td className="num py-1 text-right text-muted">
                  {Math.round(row.bikes_p10)}–{Math.round(row.bikes_p90)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Link
        to={`/station/${station.station_key}`}
        className="inline-flex min-h-11 items-center rounded-control bg-brand px-4 text-sm font-medium text-surface"
      >
        Open details
      </Link>
    </section>
  );
}
