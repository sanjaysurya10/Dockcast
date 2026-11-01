import { API_BASE } from "@/lib/config";

import type { components, paths } from "./schema";

export type City = components["schemas"]["City"];
export type Station = components["schemas"]["Station"];
export type StationForecast = components["schemas"]["StationForecast"];
export type HorizonForecast = components["schemas"]["HorizonForecast"];
export type ModelSummary = components["schemas"]["ModelSummary"];
export type ChampionModel = components["schemas"]["ChampionModel"];
export type Health = components["schemas"]["Health"];

type GetPath = {
  [P in keyof paths]: paths[P]["get"] extends { responses: unknown } ? P : never;
}[keyof paths];

type GetOperation<P extends GetPath> = NonNullable<paths[P]["get"]>;

type JsonResponse<P extends GetPath> =
  GetOperation<P>["responses"] extends { 200: { content: { "application/json": infer Body } } }
    ? Body
    : never;

type ParamsOf<P extends GetPath, Where extends "path" | "query"> =
  GetOperation<P>["parameters"] extends { [K in Where]?: infer Params }
    ? Exclude<Params, undefined>
    : never;

export interface RequestOptions<P extends GetPath> {
  path?: ParamsOf<P, "path">;
  query?: ParamsOf<P, "query">;
  signal?: AbortSignal;
}

/** API error in the PRD 15.3 shape: `{"error": {"code", "message"}}`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function buildUrl(
  base: string,
  template: string,
  pathParams?: Record<string, unknown>,
  query?: Record<string, unknown>,
): string {
  const path = template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = pathParams?.[name];
    if (value === undefined || value === null) {
      throw new Error(`missing path parameter ${name}`);
    }
    return encodeURIComponent(String(value));
  });
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) search.set(key, String(value));
  }
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  return `${base}${path}${suffix}`;
}

async function errorFrom(response: Response): Promise<ApiError> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "error" in body) {
      const { code, message } = (body as { error: { code?: unknown; message?: unknown } }).error;
      return new ApiError(response.status, String(code ?? "error"), String(message ?? ""));
    }
  } catch {
    // Body is not JSON; fall through to a generic error.
  }
  return new ApiError(response.status, "http_error", `HTTP ${response.status}`);
}

/** Typed GET against the DockCast API; types come from `openapi.json` via openapi-typescript. */
export async function apiGet<P extends GetPath>(
  path: P,
  options: RequestOptions<P> = {},
): Promise<JsonResponse<P>> {
  const url = buildUrl(
    API_BASE,
    path,
    options.path as Record<string, unknown> | undefined,
    options.query as Record<string, unknown> | undefined,
  );
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as JsonResponse<P>;
}

export type CityRisk = components["schemas"]["CityRisk"];
export type RiskStation = components["schemas"]["RiskStation"];
