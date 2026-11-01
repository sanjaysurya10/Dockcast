import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { routes } from "@/app/routes";
import type { GlobeMapProps } from "@/components/map/GlobeMap";

import { mockResponse } from "../fixtures/api";

// WebGL does not exist in jsdom: the stub prints the state counts the map would draw.
vi.mock("@/components/map/GlobeMap", () => ({
  default: ({ stations, selectedKey }: GlobeMapProps) => {
    const counts = new Map<string, number>();
    for (const station of stations) counts.set(station.state, (counts.get(station.state) ?? 0) + 1);
    return (
      <div data-testid="map-stub" data-selected={selectedKey ?? ""}>
        {[...counts].map(([state, count]) => `${state}:${count}`).join(" ")}
      </div>
    );
  },
}));

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const { status, body } = mockResponse(String(input));
      return new Response(JSON.stringify(body), { status });
    }),
  );
});

describe("routes", () => {
  it("map page: legend counts follow the horizon toggle", async () => {
    renderAt("/");
    const map = await screen.findByTestId("map-stub");
    expect(map).toHaveTextContent("ok:3 full:1 empty:1");
    fireEvent.click(screen.getByLabelText("+60"));
    await waitFor(() =>
      expect(screen.getByTestId("map-stub")).toHaveTextContent(
        "ok:2 full:1 empty:1 full-possible:1",
      ),
    );
    const legend = screen.getByTestId("legend");
    expect(within(legend).getByText("Likely empty")).toBeInTheDocument();
    expect(legend.querySelector('[data-state="full-possible"]')).toHaveTextContent("May fill1");
  });

  it("map page: at-risk list ranks from the forecast range and opens the station panel", async () => {
    renderAt("/");
    await screen.findByTestId("map-stub");
    fireEvent.click(screen.getByLabelText("+60"));
    const list = await screen.findByRole("heading", { name: "At risk at +60 min" });
    expect(list).toBeInTheDocument();
    const hardwicke = await screen.findByRole("button", { name: /HARDWICKE STREET/ });
    expect(hardwicke).toHaveTextContent("Empty by +30 min");
    expect(hardwicke).toHaveTextContent("Likely empty");
    fireEvent.click(screen.getByRole("button", { name: "Full" }));
    const full = await screen.findAllByRole("button", { name: /FOWNES|PRINCES/ });
    expect(full.map((button) => button.textContent)).toEqual([
      expect.stringContaining("FOWNES STREET UPPER"),
      expect.stringContaining("PRINCES STREET"),
    ]);
    fireEvent.click(screen.getByRole("button", { name: /FOWNES STREET UPPER/ }));
    expect(await screen.findByRole("heading", { name: "FOWNES STREET UPPER" })).toBeInTheDocument();
    expect(screen.getByTestId("map-stub")).toHaveAttribute("data-selected", "14");
    expect(screen.getByRole("link", { name: "Open details" })).toHaveAttribute(
      "href",
      "/station/14",
    );
  });

  it("map page: station search is the keyboard alternative to the map", async () => {
    renderAt("/");
    await screen.findByTestId("map-stub");
    fireEvent.change(screen.getByLabelText("Search stations"), { target: { value: "grand" } });
    fireEvent.click(await screen.findByRole("button", { name: "GRAND CANAL DOCK" }));
    expect(await screen.findByRole("heading", { name: "GRAND CANAL DOCK" })).toBeInTheDocument();
  });

  it("shows a station forecast with its P10-P90 range", async () => {
    renderAt("/station/5");
    expect(await screen.findByRole("heading", { name: "CHARLEMONT PLACE" })).toBeInTheDocument();
    expect(screen.getByText("21.9")).toBeInTheDocument();
    expect(screen.getByText("likely 17–27 (P10–P90)")).toBeInTheDocument();
  });

  it("shows not found for an unknown station", async () => {
    renderAt("/station/999");
    expect(await screen.findByRole("heading", { name: "Station not found" })).toBeInTheDocument();
  });

  it("tells a station without a forecast apart from an unknown station", async () => {
    renderAt("/station/15");
    expect(await screen.findByRole("heading", { name: "No forecast yet" })).toBeInTheDocument();
  });

  it("shows champion metrics with the run id on hover", async () => {
    renderAt("/model");
    const row = (await screen.findByText("+60 min")).closest("tr");
    expect(row).toHaveAttribute("title", "MLflow run fb0d738826974ae9982cc4e96b96e5ba");
    expect(row).toHaveTextContent("1.461");
  });

  it("always shows the data attribution", async () => {
    renderAt("/about");
    expect(await screen.findAllByText(/Smart Dublin/)).not.toHaveLength(0);
    expect(screen.getByRole("contentinfo")).toHaveTextContent("CC BY 4.0");
  });

  it("renders a 404 page for unknown routes", () => {
    renderAt("/nope");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });
});
