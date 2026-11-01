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

  it("station page: tiles, chart table, risk badge, backups and drivers", async () => {
    renderAt("/station/5");
    expect(await screen.findByRole("heading", { name: "CHARLEMONT PLACE" })).toBeInTheDocument();
    // Tiles: bikes now, docks now, +60 and +120 (PRD 16.4).
    expect(screen.getByText("likely 17–27 (P10–P90)")).toBeInTheDocument();
    expect(screen.getByText("likely 13–27 (P10–P90)")).toBeInTheDocument();
    expect(screen.queryByText("likely 19–26 (P10–P90)")).not.toBeInTheDocument(); // no +30 tile
    // Chart data table lists all three horizons.
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(await screen.findByText("Not at risk at +60")).toBeInTheDocument();
    // Backups: the 2 nearest with P50 >= 3 at +30 (real coordinates and forecasts).
    const backups = await screen.findByRole("heading", { name: "Backup stations" });
    const list = backups.parentElement?.querySelector("ul");
    expect(list).not.toBeNull();
    const names = within(list as HTMLElement).getAllByRole("link").map((link) => link.textContent);
    expect(names).toHaveLength(2);
    expect(names[0]).toContain("FOWNES STREET UPPER");
    expect(names[0]).toContain("approx. 2.0 km walk");
    // Drivers: top 4 by absolute contribution, plain language.
    const chips = await screen.findAllByRole("listitem", { name: undefined });
    const drivers = chips.map((chip) => chip.textContent ?? "").filter((text) => /[↑↓]/.test(text));
    expect(drivers).toHaveLength(4);
    expect(drivers[0]).toContain("Bikes there now and in the last 2 hours");
    expect(drivers[1]).toContain("This station's usual pattern");
    expect(drivers[1]).toContain("−2.4");
  });

  it("shows not found for an unknown station", async () => {
    renderAt("/station/999");
    expect(await screen.findByRole("heading", { name: "Station not found" })).toBeInTheDocument();
  });

  it("tells a station without a forecast apart from an unknown station", async () => {
    renderAt("/station/15");
    expect(await screen.findByRole("heading", { name: "No forecast yet" })).toBeInTheDocument();
  });

  it("model page: served metrics with the run id on hover", async () => {
    renderAt("/model");
    const served = await screen.findByRole("table", {
      name: "Backtest metrics of the served model per horizon",
    });
    const row = within(served).getByRole("rowheader", { name: "+60 min" }).closest("tr");
    expect(row).toHaveAttribute("title", "MLflow run fb0d738826974ae9982cc4e96b96e5ba");
    expect(row).toHaveTextContent("1.461");
  });

  it("model page: results table highlights the best value per column", async () => {
    renderAt("/model");
    const table = await screen.findByRole("table", { name: "+60 min" });
    const lgbm = within(table).getByRole("rowheader", { name: "LightGBM (global)" }).closest("tr");
    expect(lgbm).toHaveTextContent("1.461 (best)");
    expect(lgbm).toHaveAttribute("title", "MLflow run e4819616d7034b90abcb3adc882313da");
    const persistence = within(table).getByRole("rowheader", { name: "Persistence (no change)" });
    expect(persistence.closest("tr")).not.toHaveTextContent("(best)");
  });

  it("model page: folds, heatmap, data health and missing experiments", async () => {
    renderAt("/model");
    const folds = await screen.findByRole("list", { name: "Backtest folds" });
    expect(within(folds).getAllByRole("listitem")).toHaveLength(8);
    expect(screen.getByRole("img", { name: /115 stations/ })).toBeInTheDocument();
    expect(screen.getByText("100.0 %")).toBeInTheDocument();
    expect(screen.getByText("114")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Experiment"), { target: { value: "E7" } });
    expect(
      await screen.findByText("No backtest results for E7 are published in this database yet."),
    ).toBeInTheDocument();
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
