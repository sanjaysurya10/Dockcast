import { expect, test } from "@playwright/test";

import { mockResponse } from "../fixtures/api";

test.beforeEach(async ({ page }) => {
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const { status, body } = mockResponse(route.request().url());
    await route.fulfill({ status, json: body });
  });
});

test("home lists stations and opens a station", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dublin stations" })).toBeVisible();
  await page.getByRole("link", { name: /CHARLEMONT PLACE/ }).click();
  await expect(page).toHaveURL(/\/station\/5$/);
  await expect(page.getByRole("heading", { name: "CHARLEMONT PLACE" })).toBeVisible();
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
