# Test fixtures

Real-shaped samples cut from the actual sources on 2026-10-15 (no values invented):

- `gbfs/*.json` — live Dublin GBFS 2.3 responses, `stations` trimmed to IDs 1, 2, 118.
- `hist/dublinbike-historical-data-2022-10.csv` — format A, stations 2-3, 2022-10-30 00:00-02:59
  local (includes the repeated autumn DST hour).
- `hist/dublinbike-historical-data-2023-03.csv` — format A, stations 2-3, 2023-03-26 (spring gap).
- `hist/dublin-bikes_station_status_102025.csv` — format B, stations 1-2, 2025-10-26 00:05-01:55.
- `hist/dublin-bikes_station_status_011999.csv` — synthetic: format-B header only (empty-file case).
- `hist/unknown_header.csv` — synthetic: unrecognised header.
