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
