import type { Layer, PickingInfo } from "@deck.gl/core";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";

import { capacityRadius, MAP_STATE_TOKENS, type MapState, type MapStation } from "@/lib/risk";
import { type Rgb, tokenRgb } from "@/lib/tokens";

export type StateColours = Record<MapState, { fill: Rgb; line: Rgb }>;

/** Resolve every state's token colours (call again when the colour scheme changes). */
export function resolveColours(read: (name: string) => Rgb = tokenRgb): StateColours {
  const entries = Object.entries(MAP_STATE_TOKENS).map(([state, tokens]) => [
    state,
    { fill: read(tokens.fill), line: read(tokens.line) },
  ]);
  return Object.fromEntries(entries) as StateColours;
}

export interface StationLayerOptions {
  stations: MapStation[];
  selectedKey: number | null;
  showLabels: boolean;
  colours: StateColours;
  ink: Rgb;
  onSelect: (stationKey: number) => void;
}

/** deck.gl layers for zoom >= 9: stations sized by capacity, coloured by state (PRD 16.3). */
export function stationLayers(options: StationLayerOptions): Layer[] {
  const { stations, selectedKey, showLabels, colours, ink, onSelect } = options;
  const layers: Layer[] = [
    new ScatterplotLayer<MapStation>({
      id: "stations",
      data: stations,
      pickable: true,
      stroked: true,
      radiusUnits: "meters",
      radiusMinPixels: 5,
      lineWidthUnits: "pixels",
      getPosition: (station) => [station.lon, station.lat],
      getRadius: (station) => capacityRadius(station.capacity),
      getFillColor: (station) => colours[station.state].fill,
      getLineColor: (station) =>
        station.stationKey === selectedKey ? ink : colours[station.state].line,
      getLineWidth: (station) => (station.stationKey === selectedKey ? 3 : 1.5),
      updateTriggers: {
        getFillColor: [colours],
        getLineColor: [colours, selectedKey, ink],
        getLineWidth: [selectedKey],
      },
      onClick: (info: PickingInfo<MapStation>) => {
        if (info.object) onSelect(info.object.stationKey);
      },
    }),
  ];
  if (showLabels) {
    layers.push(
      new TextLayer<MapStation>({
        id: "station-names",
        data: stations,
        characterSet: "auto",
        getPosition: (station) => [station.lon, station.lat],
        getText: (station) => station.name,
        getSize: 12,
        getColor: ink,
        getPixelOffset: [0, -16],
        fontFamily: "IBM Plex Sans, system-ui, sans-serif",
        outlineWidth: 2,
        outlineColor: colours.ok.line,
        fontSettings: { sdf: true },
      }),
    );
  }
  return layers;
}
