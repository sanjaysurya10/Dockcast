import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { routes } from "@/app/routes";

import { mockResponse } from "../fixtures/api";

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
  it("lists stations with their state and filters by name", async () => {
    renderAt("/");
    expect(await screen.findByText("HARDWICKE STREET")).toBeInTheDocument();
    expect(screen.getByText("5 of 5 stations")).toBeInTheDocument();
    expect(screen.getAllByText("Empty")).toHaveLength(1);
    expect(screen.getAllByText("Full")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Search stations"), { target: { value: "grand" } });
    expect(screen.getByText("1 of 5 stations")).toBeInTheDocument();
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
