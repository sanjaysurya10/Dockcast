import { useState } from "react";
import { Link } from "react-router";

import { useStations } from "@/api/queries";
import { ErrorMessage, Loading } from "@/components/QueryState";
import { StateBadge } from "@/components/StateBadge";
import { walkLabel } from "@/lib/drivers";
import { nearestStations, type Position } from "@/lib/nearby";
import { stationState } from "@/lib/status";

type Locate =
  | { kind: "idle" }
  | { kind: "locating" }
  | { kind: "found"; here: Position }
  | { kind: "error"; message: string };

const DENIED = 1;

/**
 * Nearest stations (PRD 16.6). Location is asked for only after the tap, used in this page's
 * memory to sort stations, and never stored or sent anywhere.
 */
export function NearbyPage() {
  const stations = useStations();
  const [locate, setLocate] = useState<Locate>({ kind: "idle" });

  const handleLocate = () => {
    if (!("geolocation" in navigator)) {
      setLocate({
        kind: "error",
        message: "This browser cannot share a location.",
      });
      return;
    }
    setLocate({ kind: "locating" });
    navigator.geolocation.getCurrentPosition(
      (position) =>
        setLocate({
          kind: "found",
          here: {
            lat: position.coords.latitude,
            lon: position.coords.longitude,
          },
        }),
      (error) =>
        setLocate({
          kind: "error",
          message:
            error.code === DENIED
              ? "Location permission was declined. Search for a station on the map instead."
              : "Your location could not be found. Try again, or search on the map.",
        }),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
    );
  };

  const nearby =
    locate.kind === "found" && stations.data ? nearestStations(stations.data, locate.here) : [];

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Nearby stations</h1>
        <p className="text-sm text-muted">
          Your location is used only on this device to sort stations by distance. It is not stored
          or sent to DockCast.
        </p>
      </header>
      <button
        type="button"
        onClick={handleLocate}
        disabled={locate.kind === "locating"}
        className="inline-flex min-h-11 items-center rounded-control bg-brand px-4 text-sm font-medium text-surface disabled:opacity-60"
      >
        {locate.kind === "locating" ? "Finding you…" : "Use my location"}
      </button>
      <div aria-live="polite">
        {locate.kind === "error" && (
          <p role="alert" className="text-sm text-risk-empty-ink">
            {locate.message}
          </p>
        )}
        {locate.kind === "found" && stations.isPending && <Loading label="stations" />}
        {stations.isError && <ErrorMessage error={stations.error} label="stations" />}
        {nearby.length > 0 && (
          <ol
            className="divide-y divide-line rounded-card border border-line bg-surface"
            aria-label="Nearest stations"
          >
            {nearby.map(({ station, walkM }) => (
              <li key={station.station_key}>
                <Link
                  to={`/station/${station.station_key}`}
                  className="flex min-h-11 items-center justify-between gap-3 px-4 py-3 hover:bg-ground"
                >
                  <span>
                    <span className="block font-medium">{station.name}</span>
                    <span className="block text-xs text-muted">{walkLabel(walkM)}</span>
                  </span>
                  <span className="flex flex-col items-end gap-1">
                    <StateBadge state={stationState(station)} />
                    {station.now && (
                      <span className="num text-xs text-muted">
                        {station.now.bikes} bikes · {station.now.docks} docks
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
