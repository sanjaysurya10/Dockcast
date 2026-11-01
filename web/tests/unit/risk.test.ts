import { describe, expect, it } from "vitest";

import { capacityRadius, etaLabel, forecastState, mapStations, stateLabel } from "@/lib/risk";
import { hexToRgb } from "@/lib/tokens";

import { riskResponse, STATIONS } from "../fixtures/api";

function states(window: 30 | 60) {
  const risk = riskResponse(window, "empty", 200).stations;
  return Object.fromEntries(
    mapStations(STATIONS, window, risk).map((station) => [station.stationKey, station.state]),
  );
}

describe("forecast states from the real 2026-11-01 12:15 forecasts", () => {
  it("+60: Hardwicke likely empty, Fownes likely full, Princes St may fill", () => {
    expect(states(60)).toEqual({ 5: "ok", 14: "full", 15: "empty", 33: "full-possible", 68: "ok" });
  });

  it("+30 differs from +60, so the toggle changes colours", () => {
    expect(states(30)).toEqual({ 5: "ok", 14: "full-possible", 15: "empty", 33: "ok", 68: "ok" });
  });

  it("now uses the observed status", () => {
    const now = mapStations(STATIONS, "now", undefined).map((station) => station.state);
    expect(now).toEqual(["ok", "full", "empty", "ok", "ok"]);
  });

  it("a station without a forecast row has no data at a forecast horizon", () => {
    const risk = riskResponse(60, "empty", 200).stations.filter((row) => row.station_key !== 5);
    expect(mapStations(STATIONS, 60, risk)[0]?.state).toBe("unknown");
  });
});

describe("helpers", () => {
  it("likely beats possible, and empty wins a tie", () => {
    const [row] = riskResponse(60, "empty", 200).stations;
    if (!row) throw new Error("fixture has no rows");
    expect(forecastState({ ...row, empty_level: "possible", full_level: "likely" })).toBe("full");
    expect(forecastState({ ...row, empty_level: "possible", full_level: "possible" })).toBe(
      "empty-possible",
    );
  });

  it("labels forecasts as likely and keeps observed states plain", () => {
    expect(stateLabel("empty", 60)).toBe("Likely empty");
    expect(stateLabel("empty", "now")).toBe("Empty");
    expect(stateLabel("full-possible", 30)).toBe("May fill");
  });

  it("formats ETA, radius and token colours", () => {
    expect(etaLabel(60, "full")).toBe("Full by +60 min");
    expect(etaLabel(null, "empty")).toBe("");
    expect(capacityRadius(40)).toBeGreaterThan(capacityRadius(16));
    expect(hexToRgb("#0f766e")).toEqual([15, 118, 110]);
    expect(hexToRgb("not a colour")).toEqual([124, 139, 132]);
  });
});

describe("station page helpers", () => {
  it("joins history to the forecast fan, anchored at the count the model saw", async () => {
    const { forecastChartData } = await import("@/lib/chartData");
    const { FORECAST_5, HISTORY_5 } = await import("../fixtures/api");
    const data = forecastChartData(HISTORY_5, FORECAST_5);
    const anchor = data.find((point) => point.t === Date.parse(FORECAST_5.issued_at));
    expect(anchor).toMatchObject({ actual: 17, p50: 17, band: [17, 17] });
    expect(data.at(-1)?.band).toEqual([12.9375, 26.8173]);
    expect(data.map((point) => point.t)).toEqual([...data.map((point) => point.t)].sort());
  });

  it("orders drivers and labels walks", async () => {
    const { topDrivers, walkLabel } = await import("@/lib/drivers");
    const { DRIVERS_5 } = await import("../fixtures/api");
    expect(topDrivers(DRIVERS_5).map((chip) => chip.group)).toEqual([
      "lags",
      "station",
      "calendar",
      "rolling",
    ]);
    expect(walkLabel(312)).toBe("approx. 300 m walk");
    expect(walkLabel(10)).toBe("approx. 50 m walk");
    expect(walkLabel(2034)).toBe("approx. 2.0 km walk");
  });

  it("picks the best value per column", async () => {
    const { bestByMetric } = await import("@/lib/backtest");
    const { backtestResponse } = await import("../fixtures/api");
    const rows = backtestResponse("overall").rows.filter((row) => row.horizon_min === 60);
    const best = bestByMetric(rows);
    expect([...best.mae]).toEqual(["lgbm_global"]);
    expect([...best.coverage_80]).toEqual(["lgbm_global"]);
  });
});
