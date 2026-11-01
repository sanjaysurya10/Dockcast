import { useQuery } from "@tanstack/react-query";

import { CITY } from "@/lib/config";

import { apiGet } from "./client";

const MINUTE = 60_000;

/** Live data refreshes every 60 s, forecasts every 15 min (PRD 18 stack table). */
export function useStations(city: string = CITY) {
  return useQuery({
    queryKey: ["stations", city],
    queryFn: ({ signal }) => apiGet("/v1/cities/{city}/stations", { path: { city }, signal }),
    refetchInterval: MINUTE,
  });
}

export function useStationForecast(stationKey: number) {
  return useQuery({
    queryKey: ["forecast", stationKey],
    queryFn: ({ signal }) =>
      apiGet("/v1/stations/{station_key}/forecast", {
        path: { station_key: stationKey },
        signal,
      }),
    refetchInterval: 15 * MINUTE,
    enabled: Number.isInteger(stationKey) && stationKey > 0,
  });
}

export function useModelSummary() {
  return useQuery({
    queryKey: ["model-summary"],
    queryFn: ({ signal }) => apiGet("/v1/model/summary", { signal }),
    staleTime: 60 * MINUTE,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => apiGet("/health", { signal }),
    refetchInterval: MINUTE,
  });
}

export function useCities() {
  return useQuery({
    queryKey: ["cities"],
    queryFn: ({ signal }) => apiGet("/v1/cities", { signal }),
    staleTime: 60 * MINUTE,
  });
}

/** Ranked interim risk at one horizon (`basis: forecast_range`); 60 s refresh like live data. */
export function useCityRisk(
  window: number | null,
  kind: "empty" | "full",
  limit: number,
  city: string = CITY,
) {
  return useQuery({
    queryKey: ["risk", city, window, kind, limit],
    queryFn: ({ signal }) =>
      apiGet("/v1/cities/{city}/risk", {
        path: { city },
        query: { window: window ?? undefined, kind, limit },
        signal,
      }),
    refetchInterval: MINUTE,
    enabled: window !== null,
    retry: false,
  });
}

/** Net change in bikes over the last `window` minutes (PRD 10.6); fetched only while shown. */
export function useNetFlow(enabled: boolean, window = 60, city: string = CITY) {
  return useQuery({
    queryKey: ["netflow", city, window],
    queryFn: ({ signal }) =>
      apiGet("/v1/cities/{city}/netflow", { path: { city }, query: { window }, signal }),
    refetchInterval: MINUTE,
    enabled,
    retry: false,
  });
}

export function useStationHistory(stationKey: number, hours: number) {
  return useQuery({
    queryKey: ["history", stationKey, hours],
    queryFn: ({ signal }) =>
      apiGet("/v1/stations/{station_key}/history", {
        path: { station_key: stationKey },
        query: { hours },
        signal,
      }),
    refetchInterval: 5 * MINUTE,
    enabled: stationKey > 0,
  });
}

export function useAlternatives(stationKey: number, horizon: number) {
  return useQuery({
    queryKey: ["alternatives", stationKey, horizon],
    queryFn: ({ signal }) =>
      apiGet("/v1/stations/{station_key}/alternatives", {
        path: { station_key: stationKey },
        query: { horizon },
        signal,
      }),
    refetchInterval: 5 * MINUTE,
    enabled: stationKey > 0,
    retry: false,
  });
}

export function useDrivers(stationKey: number, horizon: number) {
  return useQuery({
    queryKey: ["drivers", stationKey, horizon],
    queryFn: ({ signal }) =>
      apiGet("/v1/stations/{station_key}/drivers", {
        path: { station_key: stationKey },
        query: { horizon },
        signal,
      }),
    refetchInterval: 15 * MINUTE,
    enabled: stationKey > 0,
    retry: false,
  });
}

export function useBacktest(experiment: string, sliceKind: string) {
  return useQuery({
    queryKey: ["backtest", experiment, sliceKind],
    queryFn: ({ signal }) =>
      apiGet("/v1/model/backtest", { query: { experiment, slice_kind: sliceKind }, signal }),
    staleTime: 60 * MINUTE,
    retry: false,
  });
}

export function useErrorAnalysis() {
  return useQuery({
    queryKey: ["error-analysis"],
    queryFn: ({ signal }) => apiGet("/v1/model/error-analysis", { signal }),
    staleTime: 60 * MINUTE,
    retry: false,
  });
}
