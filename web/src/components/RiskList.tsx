import { useState } from "react";

import { ApiError, type RiskStation, type Station } from "@/api/client";
import { useCityRisk } from "@/api/queries";
import { etaLabel, forecastState, type Horizon, stateLabel } from "@/lib/risk";
import { stationState } from "@/lib/status";

const TOP = 20;

type Kind = "empty" | "full";

interface Row {
  stationKey: number;
  name: string;
  bikesNow: number | null;
  detail: string;
  badge: string;
  tone: Kind;
}

function forecastRow(risk: RiskStation, kind: Kind, horizon: Horizon): Row {
  return {
    stationKey: risk.station_key,
    name: risk.name,
    bikesNow: risk.now?.bikes ?? null,
    detail:
      etaLabel(kind === "empty" ? risk.eta_empty_min : risk.eta_full_min, kind) ||
      `${risk.bikes_p50.toFixed(1)} bikes at +${risk.horizon_min} (${Math.round(
        risk.bikes_p10,
      )}–${Math.round(risk.bikes_p90)})`,
    badge: stateLabel(forecastState(risk), horizon),
    tone: kind,
  };
}

function isAtRisk(risk: RiskStation, kind: Kind): boolean {
  const level = kind === "empty" ? risk.empty_level : risk.full_level;
  return level !== "low";
}

interface RiskListProps {
  horizon: Horizon;
  stations: Station[];
  onSelect: (stationKey: number) => void;
}

/** At-risk panel (PRD 16.3 item 6): top 20 by empty or full, interim levels until M10. */
export function RiskList({ horizon, stations, onSelect }: RiskListProps) {
  const [kind, setKind] = useState<Kind>("empty");
  const window = horizon === "now" ? null : horizon;
  const risk = useCityRisk(window, kind, TOP);

  let rows: Row[] = [];
  if (horizon === "now") {
    rows = stations
      .filter((station) => stationState(station) === kind)
      .sort((a, b) => a.name.localeCompare(b.name))
      .slice(0, TOP)
      .map((station) => ({
        stationKey: station.station_key,
        name: station.name,
        bikesNow: station.now?.bikes ?? null,
        detail: `${station.now?.docks ?? 0} free docks`,
        badge: kind === "empty" ? "Empty" : "Full",
        tone: kind,
      }));
  } else if (risk.data) {
    rows = risk.data.stations
      .filter((row) => isAtRisk(row, kind))
      .map((row) => forecastRow(row, kind, horizon));
  }

  const unavailable =
    risk.error instanceof ApiError && ["data_stale", "forecast_not_found"].includes(risk.error.code);

  return (
    <section aria-labelledby="risk-heading" className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 id="risk-heading" className="font-semibold">
          At risk {horizon === "now" ? "now" : `at +${horizon} min`}
        </h2>
        <div role="group" aria-label="Risk type" className="flex gap-1">
          {(["empty", "full"] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={kind === option}
              onClick={() => setKind(option)}
              className={`min-h-11 rounded-control px-3 text-sm ${
                kind === option
                  ? option === "empty"
                    ? "bg-risk-empty-tint font-medium text-risk-empty-ink"
                    : "bg-risk-full-tint font-medium text-risk-full-ink"
                  : "text-muted hover:text-ink"
              }`}
            >
              {option === "empty" ? "Empty" : "Full"}
            </button>
          ))}
        </div>
      </div>
      {horizon !== "now" && (
        <p className="text-xs text-muted">
          Ranked from the forecast range (P10–P90), not a probability. “Likely” means the median
          forecast is empty or full; “may” means the outer 10 % of the range is.
        </p>
      )}
      {horizon !== "now" && risk.isPending && (
        <p role="status" className="text-sm text-muted">
          Loading forecasts…
        </p>
      )}
      {horizon !== "now" && risk.isError && (
        <p role="alert" className="text-sm text-risk-empty-ink">
          {unavailable
            ? "Forecasts are unavailable right now because live data is delayed."
            : "Could not load forecasts."}
        </p>
      )}
      <p aria-live="polite" className="text-sm text-muted">
        {(horizon === "now" || risk.data) &&
          `${rows.length} ${rows.length === 1 ? "station" : "stations"} ${
            kind === "empty" ? "empty" : "full"
          }${horizon === "now" ? " now" : " or at risk"}`}
      </p>
      <ol className="divide-y divide-line rounded-card border border-line">
        {rows.map((row) => (
          <li key={row.stationKey}>
            <button
              type="button"
              onClick={() => onSelect(row.stationKey)}
              className="flex min-h-11 w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-ground"
            >
              <span className="min-w-0">
                <span className="block truncate">{row.name}</span>
                <span className="num block text-xs text-muted">
                  {row.bikesNow === null ? "no live count" : `${row.bikesNow} bikes now`} ·{" "}
                  {row.detail}
                </span>
              </span>
              <span
                className={`shrink-0 rounded-control px-2 py-0.5 text-xs font-medium ${
                  row.tone === "empty"
                    ? "bg-risk-empty-tint text-risk-empty-ink"
                    : "bg-risk-full-tint text-risk-full-ink"
                }`}
              >
                {row.badge}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
