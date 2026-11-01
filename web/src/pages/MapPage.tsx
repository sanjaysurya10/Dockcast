import { lazy, Suspense, useCallback, useMemo, useState } from "react";

import { useCities, useCityRisk, useStations } from "@/api/queries";
import { HorizonToggle } from "@/components/HorizonToggle";
import { Legend } from "@/components/Legend";
import type { MapFocus } from "@/components/map/GlobeMap";
import { MapErrorBoundary } from "@/components/MapErrorBoundary";
import { ErrorMessage } from "@/components/QueryState";
import { RiskList } from "@/components/RiskList";
import { StationPanel } from "@/components/StationPanel";
import { StationSearch } from "@/components/StationSearch";
import { CITY } from "@/lib/config";
import { type Horizon, mapStations } from "@/lib/risk";
import { useDarkMode, useReducedMotion } from "@/lib/useMediaQuery";

const GlobeMap = lazy(() => import("@/components/map/GlobeMap"));

const ALL_STATIONS = 200;
const STATION_FOCUS_ZOOM = 16;

/** The command center (PRD 16.3): globe map, horizon toggle, at-risk panel, station panel. */
export function MapPage() {
  const stations = useStations();
  const cities = useCities();
  const [horizon, setHorizon] = useState<Horizon>("now");
  const [selectedKey, setSelectedKey] = useState<number | null>(null);
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const reducedMotion = useReducedMotion();
  const dark = useDarkMode();
  const risk = useCityRisk(horizon === "now" ? null : horizon, "empty", ALL_STATIONS);

  const city = cities.data?.find((item) => item.city_code === CITY);
  const centre = useMemo(
    () => (city ? { lat: city.centre_lat, lon: city.centre_lon, zoom: city.default_zoom } : null),
    [city],
  );
  // Without forecasts (stale data, none issued yet) the map falls back to the current state.
  const shownHorizon: Horizon = horizon !== "now" && risk.data ? horizon : "now";
  const markers = useMemo(
    () => mapStations(stations.data ?? [], shownHorizon, risk.data?.stations),
    [stations.data, shownHorizon, risk.data],
  );
  const selected = stations.data?.find((station) => station.station_key === selectedKey) ?? null;

  const selectFromList = useCallback(
    (stationKey: number) => {
      setSelectedKey(stationKey);
      const station = stations.data?.find((item) => item.station_key === stationKey);
      if (station) setFocus({ lat: station.lat, lon: station.lon, zoom: STATION_FOCUS_ZOOM });
    },
    [stations.data],
  );

  return (
    <div className="flex flex-1 flex-col md:flex-row">
      <h1 className="sr-only">{city?.name ?? "Dublin"} bike availability map</h1>
      <div className="relative h-[65dvh] md:h-auto md:min-h-[600px] md:flex-1">
        <MapErrorBoundary>
          <Suspense
            fallback={
              <p role="status" className="p-4 text-muted">
                Loading map…
              </p>
            }
          >
            <GlobeMap
              centre={centre}
              cityName={city?.name ?? "Dublin"}
              stations={markers}
              selectedKey={selectedKey}
              focus={focus}
              onSelect={setSelectedKey}
              reducedMotion={reducedMotion}
              dark={dark}
            />
          </Suspense>
        </MapErrorBoundary>
        <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap items-start gap-2">
          <div className="pointer-events-auto">
            <HorizonToggle value={horizon} onChange={setHorizon} />
          </div>
          {cities.data && (
            <label className="pointer-events-auto flex items-center gap-2 rounded-control border border-line bg-surface px-2 text-sm shadow-sm">
              <span className="text-muted">City</span>
              <select
                className="min-h-11 bg-transparent"
                value={CITY}
                onChange={(event) => {
                  const picked = cities.data.find((c) => c.city_code === event.target.value);
                  if (picked) {
                    setFocus({ lat: picked.centre_lat, lon: picked.centre_lon, zoom: picked.default_zoom });
                  }
                }}
              >
                {cities.data.map((option) => (
                  <option key={option.city_code} value={option.city_code}>
                    {option.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <div className="absolute bottom-10 left-3 w-56">
          <Legend stations={markers} horizon={shownHorizon} />
          {horizon !== "now" && risk.isError && (
            <p role="status" className="mt-2 rounded-control bg-surface p-2 text-xs text-risk-empty-ink">
              Forecast colours unavailable; showing the current state.
            </p>
          )}
        </div>
      </div>
      <aside
        aria-label="Stations"
        className="space-y-6 overflow-y-auto border-t border-line bg-surface p-4 md:max-h-[calc(100dvh-7.5rem)] md:w-[24rem] md:border-l md:border-t-0"
      >
        {stations.isError && <ErrorMessage error={stations.error} label="stations" />}
        <StationSearch stations={stations.data ?? []} onSelect={selectFromList} />
        {selected ? (
          <StationPanel station={selected} onClose={() => setSelectedKey(null)} />
        ) : (
          <RiskList horizon={horizon} stations={stations.data ?? []} onSelect={selectFromList} />
        )}
      </aside>
    </div>
  );
}
