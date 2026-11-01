import { useId, useState } from "react";

import type { Station } from "@/api/client";

const MAX_RESULTS = 8;

/** Station search: the map's keyboard and screen-reader alternative (PRD 16.7). */
export function StationSearch({
  stations,
  onSelect,
}: {
  stations: Station[];
  onSelect: (stationKey: number) => void;
}) {
  const [query, setQuery] = useState("");
  const id = useId();
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? stations
        .filter((station) => station.name.toLowerCase().includes(needle))
        .sort((a, b) => a.name.localeCompare(b.name))
        .slice(0, MAX_RESULTS)
    : [];
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-sm font-medium">
        Search stations
      </label>
      <input
        id={id}
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        className="min-h-11 w-full rounded-control border border-line bg-surface px-3"
      />
      {needle && (
        <ul aria-label="Matching stations" className="rounded-card border border-line">
          {matches.length === 0 && <li className="px-3 py-2 text-sm text-muted">No match</li>}
          {matches.map((station) => (
            <li key={station.station_key}>
              <button
                type="button"
                onClick={() => {
                  onSelect(station.station_key);
                  setQuery("");
                }}
                className="min-h-11 w-full px-3 text-left text-sm hover:bg-ground"
              >
                {station.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
