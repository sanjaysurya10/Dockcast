import { expect, type Page, test } from "@playwright/test";

import { mockResponse } from "../fixtures/api";

// A blank basemap keeps the tests off the tile server; the globe and deck.gl still render.
const EMPTY_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#dde2de" } }],
};

async function mockBackends(page: Page) {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const { status, body } = mockResponse(route.request().url());
    await route.fulfill({ status, json: body });
  });
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.fulfill({ status: 200, json: EMPTY_STYLE }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockBackends(page);
});

test.describe("map", () => {
  test("globe loads, spins and flies in to the station layer", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".maplibregl-canvas")).toBeVisible();
    await expect(page.getByRole("button", { name: /Dublin · 5 stations/ })).toBeVisible();
    // 2.5 s spin + 4 s fly-in, then zoom 13 shows stations instead of the city marker.
    await expect(page.locator("[data-detail]")).toHaveAttribute("data-detail", "stations", {
      timeout: 15_000,
    });
  });

  test("horizon toggle changes the colours shown", async ({ page }) => {
    await page.goto("/");
    const legend = page.getByTestId("legend");
    await expect(legend.locator('[data-state="empty"]')).toContainText("Empty1");
    await expect(legend.locator('[data-state="ok"]')).toContainText("3");
    await page.getByText("+60", { exact: true }).click();
    await expect(legend.locator('[data-state="ok"]')).toContainText("2");
    await expect(legend.locator('[data-state="full-possible"]')).toContainText("May fill1");
    await page.getByText("+30", { exact: true }).click();
    await expect(legend.locator('[data-state="full-possible"]')).toContainText("May fill1");
    await expect(legend.locator('[data-state="full"]')).toContainText("Likely full0");
  });

  test("at-risk list opens the station panel and its details page", async ({ page }) => {
    await page.goto("/");
    await page.getByText("+60", { exact: true }).click();
    await page.getByRole("button", { name: /HARDWICKE STREET/ }).click();
    await expect(page.getByRole("heading", { name: "HARDWICKE STREET" })).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: /CHARLEMONT PLACE/ }).waitFor({ state: "detached" });
    await page.getByLabel("Search stations").fill("charlemont");
    await page.getByRole("button", { name: "CHARLEMONT PLACE" }).click();
    await page.getByRole("link", { name: "Open details" }).click();
    await expect(page).toHaveURL(/\/station\/5$/);
    await expect(page.getByText("likely 17–27 (P10–P90)")).toBeVisible();
  });
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("skips the spin and fly-in", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("[data-detail]")).toHaveAttribute("data-detail", "stations", {
      timeout: 5_000,
    });
  });
});

test("navigation reaches every PRD route and attribution is visible", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Accuracy" }).click();
  await expect(page.getByRole("heading", { name: "Model accuracy" })).toBeVisible();
  await page.getByRole("link", { name: "About" }).click();
  await expect(page.getByRole("heading", { name: "About DockCast" })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toContainText("Smart Dublin");
});

test("deep links work on the preview server", async ({ page }) => {
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Model accuracy" })).toBeVisible();
});
