import { describe, expect, it } from "vitest";

import {
  championRows,
  dublinTime,
  dublinTimeOrDate,
  isStale,
  stationState,
} from "@/lib/status";

import { MODEL_SUMMARY, STATIONS } from "../fixtures/api";

describe("stationState", () => {
  it("classifies the fixture stations", () => {
    const states = Object.fromEntries(STATIONS.map((s) => [s.station_key, stationState(s)]));
    expect(states).toEqual({ 5: "ok", 14: "full", 15: "empty", 33: "ok", 68: "ok" });
  });

  it("marks closed and unknown stations", () => {
    const now = { bikes: 3, docks: 5, observed_at: "2026-11-01T12:24:00Z", is_renting: true };
    expect(stationState({ is_active: true, now: null })).toBe("unknown");
    expect(stationState({ is_active: false, now })).toBe("closed");
    expect(stationState({ is_active: true, now: { ...now, is_renting: false } })).toBe("closed");
  });
});

describe("isStale", () => {
  const now = Date.parse("2026-11-01T12:30:00Z");
  it("is stale after 5 minutes or with no run", () => {
    expect(isStale("2026-11-01T12:26:00Z", now)).toBe(false);
    expect(isStale("2026-11-01T12:24:59Z", now)).toBe(true);
    expect(isStale(null, now)).toBe(true);
  });
});

describe("championRows", () => {
  it("sorts by horizon and keeps the MLflow run id", () => {
    const rows = championRows(MODEL_SUMMARY);
    expect(rows.map((row) => row.horizonMin)).toEqual([30, 60, 120]);
    expect(rows[1]).toMatchObject({
      mae: 1.460765689208001,
      runId: "fb0d738826974ae9982cc4e96b96e5ba",
    });
  });
});

describe("dublinTime", () => {
  it("shows Europe/Dublin time across the DST change", () => {
    expect(dublinTime("2026-10-24T12:00:00Z")).toBe("13:00");
    expect(dublinTime("2026-10-25T12:00:00Z")).toBe("12:00");
  });

  it("adds the date when the time is not today", () => {
    const now = Date.parse("2026-11-01T12:30:00Z");
    expect(dublinTimeOrDate("2026-11-01T09:00:00Z", now)).toBe("09:00");
    expect(dublinTimeOrDate("2026-10-22T22:27:59Z", now)).toBe("22 Oct, 23:27");
  });
});
