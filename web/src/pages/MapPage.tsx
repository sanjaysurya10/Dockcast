import { useMemo, useState } from "react";
import { Link } from "react-router";

import { useStations } from "@/api/queries";
import { ErrorMessage, Loading } from "@/components/QueryState";
import { StateBadge } from "@/components/StateBadge";
import { stationState } from "@/lib/status";

/** M13: the station list (the map's accessible alternative, PRD 16.7). The globe map is M14. */
export function MapPage() {
  const stations = useStations();
  const [search, setSearch] = useState("");
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (stations.data ?? [])
      .filter((station) => station.name.toLowerCase().includes(needle))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [stations.data, search]);

  return (
    <section aria-labelledby="stations-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 id="stations-heading" className="text-2xl font-semibold">
            Dublin stations
          </h1>
          <p className="text-sm text-muted">Live status. The globe map arrives in the next build.</p>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          Search stations
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="min-h-11 w-64 max-w-full rounded-control border border-line bg-surface px-3"
          />
        </label>
      </div>
      {stations.isPending && <Loading label="stations" />}
      {stations.isError && <ErrorMessage error={stations.error} label="stations" />}
      {stations.data && (
        <>
          <p className="text-sm text-muted" aria-live="polite">
            {visible.length} of {stations.data.length} stations
          </p>
          <ul className="divide-y divide-line rounded-card border border-line bg-surface">
            {visible.map((station) => (
              <li key={station.station_key}>
                <Link
                  to={`/station/${station.station_key}`}
                  className="flex min-h-11 items-center justify-between gap-3 px-4 py-2 hover:bg-ground"
                >
                  <span>{station.name}</span>
                  <span className="flex items-center gap-3 text-sm">
                    {station.now && (
                      <span className="num text-muted">
                        {station.now.bikes} bikes · {station.now.docks} docks
                      </span>
                    )}
                    <StateBadge state={stationState(station)} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
