#!/usr/bin/env bash
# Nightly: export live rows older than the retention window to Parquet, upload to R2, then prune.
# Prune runs only if the upload succeeded, and itself refuses any day whose Parquet row count
# differs from the database. Requires an rclone remote named "r2" (see deploy/oracle/README.md).
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/dockcast}"
BUCKET="${R2_BUCKET:-dockcast-archive}"
COMPOSE=(docker compose -f "$REPO_DIR/deploy/oracle/docker-compose.worker.yml"
         --env-file "$REPO_DIR/deploy/oracle/.env")

"${COMPOSE[@]}" run --rm collector python -m dockcast.ingest.archive export
rclone copy --checksum /var/lib/dockcast/data/archive "r2:$BUCKET"
"${COMPOSE[@]}" run --rm collector python -m dockcast.ingest.archive prune --confirm
