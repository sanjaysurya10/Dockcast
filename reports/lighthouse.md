# Lighthouse (M18)

Measured 2026-11-05 against the live site https://dockcast.pages.dev (commit `9d9c518`), with
`npx lighthouse@12.8.2` and Playwright's Chromium (headless). Mobile is Lighthouse's default
(simulated Moto G Power, slow 4G, 4x CPU slowdown); desktop uses `--preset=desktop`. The
mobile map, accuracy, station and about pages were run three times and the median run is
kept. The first pass on a cold start scored 69 / 68 / 80 / 89, so single runs are noisy. The
other pages were run once. Raw reports: `reports/lighthouse/<page>-<mobile|desktop>.json`.

| page | form | performance | accessibility | best practices | SEO | FCP | LCP | TBT | CLS | measured (UTC) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| map | mobile | 92 | 100 | 100 | 100 | 2.7 s | 2.7 s | 20 ms | 0 | 2026-11-05T00:46 |
| map | desktop | 88 | 100 | 100 | 100 | 0.6 s | 0.7 s | 280 ms | 0.001 | 2026-11-05T00:50 |
| model | mobile | 84 | 100 | 100 | 100 | 3.0 s | 3.7 s | 30 ms | 0 | 2026-11-05T00:47 |
| model | desktop | 98 | 100 | 100 | 100 | 0.7 s | 0.9 s | 0 ms | 0.061 | 2026-11-05T00:44 |
| station-5 | mobile | 83 | 100 | 100 | 100 | 2.8 s | 3.7 s | 150 ms | 0 | 2026-11-05T00:48 |
| station-5 | desktop | 98 | 100 | 100 | 100 | 0.7 s | 1.0 s | 0 ms | 0.004 | 2026-11-05T00:45 |
| about | mobile | 89 | 100 | 100 | 100 | 2.4 s | 3.3 s | 10 ms | 0 | 2026-11-05T00:49 |
| about | desktop | 99 | 100 | 100 | 100 | 0.6 s | 0.9 s | 0 ms | 0 | 2026-11-05T00:44 |
| nearby | mobile | 91 | 100 | 100 | 100 | 2.8 s | 2.8 s | 10 ms | 0 | 2026-11-05T00:45 |
| nearby | desktop | 100 | 100 | 100 | 100 | 0.6 s | 0.6 s | 0 ms | 0 | 2026-11-05T00:45 |

## Against the M18 target (≥ 90 performance and accessibility)

- **Accessibility: met.** 100 on every page, in both forms.
- **Performance: met on 6 of 10.** The misses are map desktop (88), and on mobile model (84),
  station (83) and about (89).
- **Before M18**, map mobile was 33: the WebGL globe (1.7 MB chunk) loaded with the page.
  Two changes produced the scores above:
  - pages are split into chunks, and the globe starts after first paint (or on tap on phones);
  - charts render only when scrolled into view, and space is reserved for late content.
    This brought model desktop from 70 to 98 (CLS 0.77 to 0.061).
- **Why the remaining mobile misses are hard:** LCP on the text pages (3.3-3.7 s) is mostly
  render delay while the single-page app's JavaScript (358 KB entry: React, React Router,
  TanStack Query) downloads and runs under the 4x CPU throttle. Closing that gap would need
  prerendered HTML, which is a build change and a new dependency.
- **Why map desktop misses:** the globe's initial render costs 280 ms of blocking time
  once the browser is idle.
- **Model mobile CLS:** one of three runs measured 0.167, because the backtest table
  sometimes arrives after the reserved space is laid out.
