import { Link } from "react-router";

import { useAlternatives } from "@/api/queries";
import { walkLabel } from "@/lib/drivers";

const HORIZON = 30;

/** Two nearest stations with at least 3 bikes forecast at +30 (PRD 16.4). */
export function Alternatives({ stationKey }: { stationKey: number }) {
  const alternatives = useAlternatives(stationKey, HORIZON);
  return (
    <section aria-labelledby="alternatives-heading" className="space-y-2">
      <h2 id="alternatives-heading" className="text-lg font-semibold">
        Backup stations
      </h2>
      <p className="text-sm text-muted">
        The nearest stations forecast to have at least 3 bikes in {HORIZON} min.
      </p>
      {alternatives.isError && (
        <p className="text-sm text-muted">No backup stations are available right now.</p>
      )}
      {alternatives.data && alternatives.data.alternatives.length === 0 && (
        <p className="text-sm text-muted">No nearby station is forecast to have 3 or more bikes.</p>
      )}
      {alternatives.data && alternatives.data.alternatives.length > 0 && (
        <ul className="divide-y divide-line rounded-card border border-line bg-surface">
          {alternatives.data.alternatives.map((alt) => (
            <li key={alt.station_key}>
              <Link
                to={`/station/${alt.station_key}`}
                className="flex min-h-11 items-center justify-between gap-3 px-4 py-2 hover:bg-ground"
              >
                <span>
                  <span className="block">{alt.name}</span>
                  <span className="block text-xs text-muted">{walkLabel(alt.walk_m)}</span>
                </span>
                <span className="num text-sm">
                  {alt.bikes_p50.toFixed(0)} bikes at +{HORIZON}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
