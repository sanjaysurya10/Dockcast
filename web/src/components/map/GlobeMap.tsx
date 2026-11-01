import "maplibre-gl/dist/maplibre-gl.css";

import { MapboxOverlay } from "@deck.gl/mapbox";
import { Map as MapLibreMap, Marker, NavigationControl } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import { LABEL_ZOOM, MAP_STYLE_DARK, MAP_STYLE_LIGHT, STATION_ZOOM } from "@/lib/config";
import type { MapStation } from "@/lib/risk";
import { tokenRgb } from "@/lib/tokens";

import { resolveColours, stationLayers } from "./StationLayer";

export interface MapFocus {
  lat: number;
  lon: number;
  zoom: number;
}

export interface GlobeMapProps {
  centre: MapFocus | null;
  cityName: string;
  stations: MapStation[];
  selectedKey: number | null;
  focus: MapFocus | null;
  onSelect: (stationKey: number) => void;
  reducedMotion: boolean;
  dark: boolean;
}

const WORLD = { center: [-20, 35] as [number, number], zoom: 1.2 };
const SPIN_DEG_PER_S = 3;
const SPIN_MS = 2500;
const FLY_MS = 4000;
const INTERACTIONS = ["mousedown", "touchstart", "wheel", "keydown"] as const;

type Detail = "city" | "stations" | "labels";

function detailAt(zoom: number): Detail {
  if (zoom < STATION_ZOOM) return "city";
  return zoom < LABEL_ZOOM ? "stations" : "labels";
}

/**
 * MapLibre globe (PRD 16.3): spins slowly, then flies to the city; below zoom 9 one city marker,
 * from zoom 9 deck.gl station circles, from zoom 15 station names.
 */
export default function GlobeMap(props: GlobeMapProps) {
  const { centre, cityName, stations, selectedKey, focus, onSelect, reducedMotion, dark } = props;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const introDone = useRef(false);
  const initialDark = useRef(dark);
  const [detail, setDetail] = useState<Detail>("city");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibreMap({
      container: container.current,
      style: initialDark.current ? MAP_STYLE_DARK : MAP_STYLE_LIGHT,
      center: WORLD.center,
      zoom: WORLD.zoom,
      attributionControl: { compact: false },
    });
    map.addControl(new NavigationControl({ visualizePitch: true }), "top-right");
    const overlay = new MapboxOverlay({ interleaved: true, layers: [] });
    map.addControl(overlay);
    map.on("style.load", () => map.setProjection({ type: "globe" }));
    map.on("load", () => setReady(true));
    map.on("zoom", () => setDetail(detailAt(map.getZoom())));
    mapRef.current = map;
    overlayRef.current = overlay;
    return () => {
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

  // Switch basemap with the colour scheme; style.load re-applies the globe projection.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || dark === initialDark.current) return;
    initialDark.current = dark;
    map.setStyle(dark ? MAP_STYLE_DARK : MAP_STYLE_LIGHT);
  }, [dark]);

  // Intro: spin the globe (about 3 deg/s) until the user interacts or 2.5 s pass, then fly in.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !centre || introDone.current) return;
    const target = { center: [centre.lon, centre.lat] as [number, number], zoom: centre.zoom };
    if (reducedMotion) {
      introDone.current = true;
      map.jumpTo(target);
      return;
    }
    let frame = 0;
    let last = performance.now();
    const start = last;
    const element = map.getCanvasContainer();
    const cancel = () => {
      cancelAnimationFrame(frame);
      INTERACTIONS.forEach((name) => element.removeEventListener(name, userTookOver));
    };
    const userTookOver = () => {
      introDone.current = true;
      cancel();
    };
    const spin = (now: number) => {
      if (now - start >= SPIN_MS) {
        introDone.current = true;
        cancel();
        map.flyTo({ ...target, duration: FLY_MS, essential: false });
        return;
      }
      const centreNow = map.getCenter();
      map.setCenter([centreNow.lng + (SPIN_DEG_PER_S * (now - last)) / 1000, centreNow.lat]);
      last = now;
      frame = requestAnimationFrame(spin);
    };
    INTERACTIONS.forEach((name) => element.addEventListener(name, userTookOver));
    frame = requestAnimationFrame(spin);
    return cancel;
  }, [ready, centre, reducedMotion]);

  // Below zoom 9: one marker for the city, with the station count; click to fly in.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !centre || detail !== "city") return;
    const button = document.createElement("button");
    button.type = "button";
    button.className =
      "rounded-card border border-line bg-surface px-3 py-1 text-sm font-medium text-ink shadow";
    button.textContent = `${cityName} · ${stations.length} stations`;
    button.addEventListener("click", () => {
      const target = { center: [centre.lon, centre.lat] as [number, number], zoom: centre.zoom };
      if (reducedMotion) map.jumpTo(target);
      else map.flyTo({ ...target, duration: FLY_MS / 2 });
    });
    const marker = new Marker({ element: button })
      .setLngLat([centre.lon, centre.lat])
      .addTo(map);
    // MapLibre labels every marker "Map marker"; name it after what it does instead.
    button.setAttribute("aria-label", `${button.textContent}: zoom to the city`);
    return () => {
      marker.remove();
    };
  }, [centre, cityName, detail, reducedMotion, stations.length]);

  // Fly to a station picked from the list (PRD 16.3 item 5).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focus) return;
    introDone.current = true;
    const target = { center: [focus.lon, focus.lat] as [number, number], zoom: focus.zoom };
    if (reducedMotion) map.jumpTo(target);
    else map.flyTo({ ...target, duration: 1500 });
  }, [focus, reducedMotion]);

  // The station layer only rebuilds when its inputs change (PRD 16.8).
  // Token values change with the colour scheme, so `dark` is the cache key.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const colours = useMemo(() => resolveColours(), [dark]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ink = useMemo(() => tokenRgb("--ink"), [dark]);
  const layers = useMemo(
    () =>
      detail === "city"
        ? []
        : stationLayers({
            stations,
            selectedKey,
            showLabels: detail === "labels",
            colours,
            ink,
            onSelect,
          }),
    [detail, stations, selectedKey, colours, ink, onSelect],
  );
  useEffect(() => {
    overlayRef.current?.setProps({ layers });
  }, [layers]);

  return (
    // MapLibre sets `position: relative` on its container, so the sizing lives on a wrapper.
    <div
      className="absolute inset-0"
      role="region"
      aria-label={`Map of ${cityName} stations. Use the station list for keyboard access.`}
      data-detail={detail}
    >
      <div ref={container} className="h-full w-full" />
    </div>
  );
}
