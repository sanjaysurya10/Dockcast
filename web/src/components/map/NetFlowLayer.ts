import { ScatterplotLayer } from "@deck.gl/layers";

import { type FlowDirection, type NetFlowPoint, pulse, ringRadius } from "@/lib/netflow";
import type { Rgb } from "@/lib/tokens";

export type FlowColours = Record<FlowDirection, Rgb>;

/**
 * Net flow rings (PRD 16.3 item 8): inflow pulses outward in the brand colour, outflow pulses
 * inward in muted ink, sized by |net|. `phase` null draws still rings (reduced motion).
 */
export function netFlowLayer(
  points: NetFlowPoint[],
  colours: FlowColours,
  phase: number | null,
): ScatterplotLayer<NetFlowPoint> {
  const shape = (point: NetFlowPoint) =>
    phase === null ? { scale: 1, alpha: 220 } : pulse(point.direction, phase);
  return new ScatterplotLayer<NetFlowPoint>({
    id: "net-flow",
    data: points,
    pickable: false,
    filled: false,
    stroked: true,
    radiusUnits: "meters",
    radiusMinPixels: 8,
    lineWidthUnits: "pixels",
    getPosition: (point) => [point.lon, point.lat],
    getRadius: (point) => ringRadius(point.net) * shape(point).scale,
    getLineColor: (point) => [...colours[point.direction], shape(point).alpha],
    getLineWidth: (point) => (point.direction === "inflow" ? 2.5 : 2),
    updateTriggers: { getRadius: [phase], getLineColor: [phase, colours] },
  });
}
