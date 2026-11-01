import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AUTOPILOT_FLY_MS, AUTOPILOT_HOLD_MS, autopilotStops } from "@/lib/autopilot";
import { nearestStations } from "@/lib/nearby";
import { netFlowLabel, netFlowSummary, pulse, ringRadius } from "@/lib/netflow";
import { useAutopilot } from "@/lib/useAutopilot";

import { NET_FLOW, riskResponse, STATIONS } from "../fixtures/api";

describe("net flow from the real 2026-11-01 11:15-12:15 UTC window", () => {
  it("draws rings only for non-zero, non-excluded stations", () => {
    const summary = netFlowSummary(STATIONS, NET_FLOW);
    expect(summary.points.map((p) => [p.stationKey, p.net, p.direction])).toEqual([
      [14, 3, "inflow"],
      [33, -3, "outflow"],
      [68, 1, "inflow"],
    ]);
    expect(summary).toMatchObject({
      inflow: 2,
      outflow: 1,
      unchanged: 1,
      excluded: 1,
    });
  });

  it("is empty without data", () => {
    expect(netFlowSummary(STATIONS, undefined).points).toEqual([]);
  });

  it("ring size grows with |net| and is capped", () => {
    expect(ringRadius(3)).toBe(ringRadius(-3));
    expect(ringRadius(4)).toBeGreaterThan(ringRadius(1));
    expect(ringRadius(10_000)).toBe(220);
  });

  it("inflow pulses outward, outflow inward, both fading", () => {
    expect(pulse("inflow", 0.9).scale).toBeGreaterThan(pulse("inflow", 0.1).scale);
    expect(pulse("outflow", 0.9).scale).toBeLessThan(pulse("outflow", 0.1).scale);
    expect(pulse("inflow", 0.9).alpha).toBeLessThan(pulse("inflow", 0.1).alpha);
  });

  it("labels say inflow or outflow", () => {
    expect(netFlowLabel(3)).toBe("+3 bikes (inflow)");
    expect(netFlowLabel(-1)).toBe("-1 bike (outflow)");
  });
});

describe("autopilot stops", () => {
  it("tours likely before possible and skips low risk (+60 forecast)", () => {
    const stops = autopilotStops(riskResponse(60, "empty", 200).stations);
    const keys = stops.map((stop) => stop.station_key);
    expect(new Set(keys.slice(0, 2))).toEqual(new Set([14, 15]));
    expect(keys.slice(2)).toEqual([33]);
  });

  it("caps the tour", () => {
    expect(autopilotStops(riskResponse(60, "empty", 200).stations, 1)).toHaveLength(1);
  });
});

describe("useAutopilot", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const stops = autopilotStops(riskResponse(60, "empty", 200).stations);

  it("visits each stop after fly + hold and wraps", () => {
    const onVisit = vi.fn();
    const { result } = renderHook(() => useAutopilot({ stops, reducedMotion: false, onVisit }));
    act(() => result.current.start());
    expect(onVisit).toHaveBeenLastCalledWith(stops[0]);
    act(() => vi.advanceTimersByTime(AUTOPILOT_FLY_MS + AUTOPILOT_HOLD_MS));
    expect(onVisit).toHaveBeenLastCalledWith(stops[1]);
    act(() => vi.advanceTimersByTime(AUTOPILOT_FLY_MS + AUTOPILOT_HOLD_MS));
    expect(onVisit).toHaveBeenLastCalledWith(stops[2]);
    act(() => vi.advanceTimersByTime(AUTOPILOT_FLY_MS + AUTOPILOT_HOLD_MS));
    expect(onVisit).toHaveBeenLastCalledWith(stops[0]);
    expect(result.current.active).toBe(true);
  });

  it("reduced motion keeps only the hold", () => {
    const onVisit = vi.fn();
    const { result } = renderHook(() => useAutopilot({ stops, reducedMotion: true, onVisit }));
    act(() => result.current.start());
    act(() => vi.advanceTimersByTime(AUTOPILOT_HOLD_MS));
    expect(onVisit).toHaveBeenCalledTimes(2);
  });

  it("any user input stops it", () => {
    const onVisit = vi.fn();
    const { result } = renderHook(() => useAutopilot({ stops, reducedMotion: false, onVisit }));
    act(() => result.current.start());
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft" }));
    });
    expect(result.current.active).toBe(false);
    act(() => vi.advanceTimersByTime(AUTOPILOT_FLY_MS + AUTOPILOT_HOLD_MS));
    expect(onVisit).toHaveBeenCalledTimes(1);
  });

  it("does not start without stops", () => {
    const { result } = renderHook(() =>
      useAutopilot({ stops: [], reducedMotion: false, onVisit: vi.fn() }),
    );
    act(() => result.current.start());
    expect(result.current.active).toBe(false);
  });
});

describe("nearby", () => {
  it("sorts stations by approximate walk from a point (Charlemont Place)", () => {
    const nearby = nearestStations(STATIONS, { lat: 53.330704, lon: -6.260004 }, 2);
    expect(nearby.map((n) => n.station.station_key)).toEqual([5, 14]);
    expect(nearby[0]?.walkM).toBeCloseTo(0);
    expect(nearby[1]?.walkM).toBeGreaterThan(1500);
  });
});
