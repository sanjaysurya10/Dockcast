// Records the README demo: drives the live site and saves timestamped PNG frames.
// Usage: node scripts/demo-frames.mjs <out-dir> [url]   (then `make demo-gif` assembles them)
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

import { chromium } from "@playwright/test";

const outDir = process.argv[2];
const url = process.argv[3] ?? "https://dockcast.pages.dev";
if (!outDir) throw new Error("usage: node scripts/demo-frames.mjs <out-dir> [url]");

const FRAME_MS = 150;
const SIZE = { width: 1100, height: 680 };

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: SIZE, colorScheme: "light" });
const started = Date.now();
let recording = true;
let index = 0;

async function record() {
  while (recording) {
    const elapsed = Date.now() - started;
    const name = `${String(index++).padStart(4, "0")}_${elapsed}.png`;
    await page.screenshot({ path: join(outDir, name) }).catch(() => undefined);
    const wait = FRAME_MS - (Date.now() - started - elapsed);
    if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
  }
}

const hold = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await page.goto(url);
const recorder = record();
// Globe spin and fly-in to Dublin (2.5 s + 4 s).
await page.locator("[data-detail='stations']").waitFor({ timeout: 30_000 });
await hold(1500);
await page.getByText("+60", { exact: true }).click();
await hold(2000);
await page.getByRole("button", { name: "Net flow" }).click();
await hold(3000);
await page.getByRole("button", { name: "Net flow" }).click();
await page.getByRole("button", { name: "Autopilot" }).click();
await hold(12_500);
await page.getByRole("button", { name: "Stop autopilot" }).click();
await hold(1500);
await page.getByRole("link", { name: "Accuracy" }).click();
await page.getByRole("table", { name: "+60 min" }).waitFor();
await hold(2500);
await page.mouse.wheel(0, 1400);
await hold(2500);
recording = false;
await recorder;
await browser.close();
console.log(`${index} frames in ${outDir}`);
