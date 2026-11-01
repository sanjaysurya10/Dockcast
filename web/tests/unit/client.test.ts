import { describe, expect, it, vi } from "vitest";

import { ApiError, apiGet, buildUrl } from "@/api/client";

describe("buildUrl", () => {
  it("fills path parameters and skips empty query values", () => {
    expect(
      buildUrl("http://api", "/v1/stations/{station_key}/history", { station_key: 5 }, {
        hours: 24,
        unused: undefined,
      }),
    ).toBe("http://api/v1/stations/5/history?hours=24");
  });

  it("encodes path parameters and rejects missing ones", () => {
    expect(buildUrl("", "/v1/cities/{city}/stations", { city: "a b" })).toBe(
      "/v1/cities/a%20b/stations",
    );
    expect(() => buildUrl("", "/v1/cities/{city}/stations", {})).toThrow("city");
  });
});

describe("apiGet", () => {
  it("raises ApiError with the PRD 15.3 code and message", async () => {
    const body = { error: { code: "station_not_found", message: "no station 999" } };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(body), { status: 404 })),
    );
    const call = apiGet("/v1/stations/{station_key}/forecast", { path: { station_key: 999 } });
    await expect(call).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      code: "station_not_found",
      message: "no station 999",
    });
  });

  it("falls back to a generic error for non-JSON bodies", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("bad gateway", { status: 502 })));
    const error = await apiGet("/health").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("http_error");
  });
});
