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

/** Phones start the globe on a tap; wide screens start it on their own once idle. */
async function openMap(page: Page, isMobile: boolean) {
  await page.goto("/");
  if (isMobile) await page.getByRole("button", { name: "Show map" }).click();
}

test.describe("map", () => {
  test("globe loads, spins and flies in to the station layer", async ({ page, isMobile }) => {
    await openMap(page, isMobile);
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

  test("skips the spin and fly-in", async ({ page, isMobile }) => {
    await openMap(page, isMobile);
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

test("station page draws the forecast chart", async ({ page }) => {
  await page.goto("/station/5");
  await expect(page.getByRole("heading", { name: "CHARLEMONT PLACE" })).toBeVisible();
  await expect(page.locator(".recharts-surface").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Backup stations" })).toBeVisible();
  await expect(page.getByText("Bikes there now and in the last 2 hours")).toBeVisible();
});

test("model page draws its charts", async ({ page }) => {
  await page.goto("/model");
  await expect(page.getByRole("table", { name: "+60 min" })).toBeVisible();
  // Charts below the fold render when they scroll into view.
  await expect(page.locator(".recharts-surface")).toHaveCount(0);
  await page.getByRole("heading", { name: "Where the model is wrong" }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("img", { name: /115 stations/ })).toBeVisible();
  await page.getByRole("heading", { name: "Calibration" }).scrollIntoViewIfNeeded();
  await expect(page.locator(".recharts-surface")).toHaveCount(2);
});

test.describe("map modes", () => {
  test("net flow toggle draws rings and explains they are net change, not trips", async ({
    page,
  }) => {
    await page.goto("/");
    const toggle = page.getByRole("button", { name: "Net flow" });
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    const legend = page.getByTestId("net-flow-legend");
    await expect(legend).toContainText("not trips");
    await expect(legend).toContainText("Excluded (rebalancing, closed or no data)1");
    await expect(page.locator("[data-net-flow]")).toHaveAttribute("data-net-flow", "3");
    await toggle.click();
    await expect(legend).toBeHidden();
  });

  test("autopilot tours at-risk stations and stops on user input", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Autopilot" }).click();
    const status = page.getByTestId("autopilot-status");
    await expect(status).toContainText(/station 1 of 3/);
    await expect(page.getByRole("button", { name: "Stop autopilot" })).toBeVisible();
    await expect(page.locator("#station-panel-heading")).toBeVisible();
    await page.getByLabel("Search stations").press("a");
    await expect(page.getByRole("button", { name: "Autopilot" })).toBeVisible();
    await expect(status).toBeEmpty();
  });
});

test.describe("reduced motion autopilot", () => {
  test.use({ reducedMotion: "reduce" });

  test("jumps between stops, holding 4 s each", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Autopilot" }).click();
    const status = page.getByTestId("autopilot-status");
    await expect(status).toContainText(/station 1 of 3/);
    await expect(status).toContainText(/station 2 of 3/, { timeout: 6_000 });
  });
});

test.describe("nearby", () => {
  test.use({
    geolocation: { latitude: 53.3307, longitude: -6.26 },
    permissions: ["geolocation"],
  });

  test("asks for location only after the tap, then lists the nearest stations", async ({
    page,
  }) => {
    await page.goto("/nearby");
    await expect(page.getByRole("list", { name: "Nearest stations" })).toHaveCount(0);
    await page.getByRole("button", { name: "Use my location" }).click();
    const list = page.getByRole("list", { name: "Nearest stations" });
    await expect(list.getByRole("link").first()).toContainText("CHARLEMONT PLACE");
    await expect(list.getByRole("link")).toHaveCount(5);
  });
});

test("phones get a bottom nav and a station sheet over the map", async ({ page, isMobile }) => {
  test.skip(!isMobile, "phone layout only");
  await page.goto("/");
  const sections = page.getByRole("navigation", { name: "Sections" });
  await expect(sections.getByRole("link")).toHaveText(["Nearby", "Map", "Accuracy"]);
  const sheet = page.getByRole("complementary", { name: "Stations" });
  await expect(sheet).toHaveAttribute("data-expanded", "false");
  await page.getByRole("button", { name: "Expand stations" }).click();
  await expect(sheet).toHaveAttribute("data-expanded", "true");
  for (const link of await sections.getByRole("link").all()) {
    expect((await link.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
  await sections.getByRole("link", { name: "Nearby" }).click();
  await expect(page.getByRole("heading", { name: "Nearby stations" })).toBeVisible();
});

test("a failing basemap falls back to a plain background and still draws stations", async ({
  page,
  isMobile,
}) => {
  await page.unroute("https://tiles.openfreemap.org/**");
  await page.route("https://tiles.openfreemap.org/**", (route) => route.fulfill({ status: 503 }));
  await openMap(page, isMobile);
  await expect(page.getByText("Basemap unavailable")).toBeVisible();
  await expect(page.locator("[data-detail]")).toHaveAttribute("data-detail", "stations", {
    timeout: 15_000,
  });
});

test("phones show stations first and load the globe only when asked", async ({ page, isMobile }) => {
  test.skip(!isMobile, "phone layout only");
  await page.goto("/");
  await expect(page.getByRole("complementary", { name: "Stations" })).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toHaveCount(0);
  await page.getByRole("button", { name: "Show map" }).click();
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
});
