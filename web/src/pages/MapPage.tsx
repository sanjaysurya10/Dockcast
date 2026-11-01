import { lazy, Suspense, useCallback, useMemo, useState } from "react";

import type { RiskStation } from "@/api/client";
import { useCities, useCityRisk, useNetFlow, useStations } from "@/api/queries";
import { BottomSheet } from "@/components/BottomSheet";
import { HorizonToggle } from "@/components/HorizonToggle";
import { Legend } from "@/components/Legend";
import type { MapFocus } from "@/components/map/GlobeMap";
import { MapErrorBoundary } from "@/components/MapErrorBoundary";
import { MapTools } from "@/components/MapTools";
import { NetFlowLegend } from "@/components/NetFlowLegend";
import { ErrorMessage } from "@/components/QueryState";
import { RiskList } from "@/components/RiskList";
import { StationPanel } from "@/components/StationPanel";
import { StationSearch } from "@/components/StationSearch";
import { AUTOPILOT_FLY_MS, AUTOPILOT_PITCH, AUTOPILOT_ZOOM, autopilotStops } from "@/lib/autopilot";
import { CITY } from "@/lib/config";
import { netFlowSummary } from "@/lib/netflow";
import { type Horizon, mapStations } from "@/lib/risk";
import { useAutopilot } from "@/lib/useAutopilot";
import { useDarkMode, useReducedMotion } from "@/lib/useMediaQuery";

const GlobeMap = lazy(() => import("@/components/map/GlobeMap"));

const ALL_STATIONS = 200;
const STATION_FOCUS_ZOOM = 16;
const AUTOPILOT_DEFAULT_WINDOW = 60;

/** The command center (PRD 16.3): globe map, horizon toggle, at-risk panel, station panel. */
export function MapPage() {
  const stations = useStations();
  const cities = useCities();
  const [horizon, setHorizon] = useState<Horizon>("now");
  const [selectedKey, setSelectedKey] = useState<number | null>(null);
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [netFlowOn, setNetFlowOn] = useState(false);
  const [sheetExpanded, setSheetExpanded] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const handleBasemapFailed = useCallback(() => setBasemapFailed(true), []);
  const reducedMotion = useReducedMotion();
  const dark = useDarkMode();
  // "Now" colours need no forecast, but autopilot still tours the +60 risk ranking.
  const risk = useCityRisk(
    horizon === "now" ? AUTOPILOT_DEFAULT_WINDOW : horizon,
    "empty",
    ALL_STATIONS,
  );
  const netFlow = useNetFlow(netFlowOn);

  const city = cities.data?.find((item) => item.city_code === CITY);
  const centre = useMemo(
    () =>
      city
        ? {
            lat: city.centre_lat,
            lon: city.centre_lon,
            zoom: city.default_zoom,
          }
        : null,
    [city],
  );
  // Without forecasts (stale data, none issued yet) the map falls back to the current state.
  const shownHorizon: Horizon = horizon !== "now" && risk.data ? horizon : "now";
  const markers = useMemo(
    () => mapStations(stations.data ?? [], shownHorizon, risk.data?.stations),
    [stations.data, shownHorizon, risk.data],
  );
  const flow = useMemo(
    () => netFlowSummary(stations.data ?? [], netFlow.data),
    [stations.data, netFlow.data],
  );
  const selected = stations.data?.find((station) => station.station_key === selectedKey) ?? null;

  const selectFromList = useCallback(
    (stationKey: number) => {
      setSelectedKey(stationKey);
      const station = stations.data?.find((item) => item.station_key === stationKey);
      if (station)
        setFocus({
          lat: station.lat,
          lon: station.lon,
          zoom: STATION_FOCUS_ZOOM,
        });
    },
    [stations.data],
  );
  const selectOnMap = useCallback((stationKey: number) => {
    setSelectedKey(stationKey);
    setSheetExpanded(true);
  }, []);

  const stops = useMemo(() => autopilotStops(risk.data?.stations ?? []), [risk.data]);
  const visit = useCallback((stop: RiskStation) => {
    setSelectedKey(stop.station_key);
    setSheetExpanded(true);
    setFocus({
      lat: stop.lat,
      lon: stop.lon,
      zoom: AUTOPILOT_ZOOM,
      pitch: AUTOPILOT_PITCH,
      durationMs: AUTOPILOT_FLY_MS,
    });
  }, []);
  const autopilot = useAutopilot({ stops, reducedMotion, onVisit: visit });

  return (
    <div className="relative flex min-h-0 flex-1 flex-col md:flex-row">
      <h1 className="sr-only">{city?.name ?? "Dublin"} bike availability map</h1>
      <div className="relative min-h-0 flex-1 md:min-h-[600px]">
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
              onSelect={selectOnMap}
              reducedMotion={reducedMotion}
              dark={dark}
              netFlow={netFlowOn && netFlow.data ? flow.points : null}
              onBasemapFailed={handleBasemapFailed}
            />
          </Suspense>
        </MapErrorBoundary>
        <div className="pointer-events-none absolute left-3 right-14 top-3 flex flex-wrap items-start gap-2">
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
                    setFocus({
                      lat: picked.centre_lat,
                      lon: picked.centre_lon,
                      zoom: picked.default_zoom,
                    });
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
          <div className="pointer-events-auto">
            <MapTools
              netFlowOn={netFlowOn}
              onNetFlow={setNetFlowOn}
              autopilotOn={autopilot.active}
              autopilotStops={stops.length}
              onAutopilot={autopilot.active ? autopilot.stop : autopilot.start}
            />
          </div>
        </div>
        <div className="absolute bottom-40 left-3 flex w-60 flex-col-reverse md:bottom-10 md:flex-col">
          {basemapFailed && (
            <p
              role="status"
              className="mt-2 rounded-control border border-line bg-surface p-2 text-xs shadow-sm md:mb-2 md:mt-0"
            >
              Basemap unavailable; stations are shown on a plain background.
            </p>
          )}
          <button
            type="button"
            aria-expanded={keyOpen}
            aria-controls="map-key"
            onClick={() => setKeyOpen((open) => !open)}
            className="inline-flex min-h-11 w-fit items-center rounded-control border border-line bg-surface px-3 text-sm shadow-sm md:hidden"
          >
            {keyOpen ? "Hide map key" : "Map key"}
          </button>
          <div
            id="map-key"
            className={`${keyOpen ? "block" : "hidden"} mb-2 max-h-[35dvh] space-y-2 overflow-y-auto md:mb-0 md:block md:max-h-none md:overflow-visible`}
          >
            <Legend stations={markers} horizon={shownHorizon} />
            {horizon !== "now" && risk.isError && (
              <p
                role="status"
                className="rounded-control bg-surface p-2 text-xs text-risk-empty-ink"
              >
                Forecast colours unavailable; showing the current state.
              </p>
            )}
            {netFlowOn && netFlow.data && (
              <NetFlowLegend
                summary={flow}
                windowMin={netFlow.data.window_min}
                ts={netFlow.data.ts}
              />
            )}
            {netFlowOn && netFlow.isError && (
              <p
                role="status"
                className="rounded-control bg-surface p-2 text-xs text-risk-empty-ink"
              >
                Net flow unavailable right now.
              </p>
            )}
          </div>
        </div>
        <p aria-live="polite" className="sr-only" data-testid="autopilot-status">
          {autopilot.current
            ? `Autopilot: station ${autopilot.index + 1} of ${stops.length}, ${autopilot.current.name}`
            : ""}
        </p>
      </div>
      <BottomSheet
        label="Stations"
        expanded={sheetExpanded}
        onToggle={() => setSheetExpanded((open) => !open)}
      >
        {stations.isError && <ErrorMessage error={stations.error} label="stations" />}
        <StationSearch stations={stations.data ?? []} onSelect={selectFromList} />
        {selected ? (
          <StationPanel station={selected} onClose={() => setSelectedKey(null)} />
        ) : (
          <RiskList horizon={horizon} stations={stations.data ?? []} onSelect={selectFromList} />
        )}
      </BottomSheet>
    </div>
  );
}
