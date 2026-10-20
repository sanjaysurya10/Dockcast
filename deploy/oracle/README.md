# Cloud collector (PRD 18.2)

Always-on worker on an Oracle Cloud Always Free VM, writing to a Supabase Postgres, nightly
Parquet archive to Cloudflare R2, and a GitHub Actions fallback every 5 min.
**The owner creates every account and secret; nothing here creates accounts.**

## 1. Accounts (owner)

1. **Oracle Cloud** — Always Free tenancy. Pick a home region with A1 capacity (busy regions often
   report "Out of capacity"). Optional: upgrade to Pay-As-You-Go to avoid idle reclamation
   (stays $0 inside Always Free limits; reported by secondary sources, not stated by Oracle).
2. **Supabase** — one free project in an EU region. Copy the **session pooler** connection
   string (IPv4) from *Project settings → Database*; check on that page whether the direct host
   is IPv6-only before choosing it.
3. **Cloudflare** — R2 bucket `dockcast-archive`; create an R2 API token (Object Read & Write,
   that bucket only).
4. **GitHub** — repository secrets `DATABASE_URL` (and optionally `CONTACT_EMAIL`) for the
   fallback workflow `.github/workflows/collector.yml`.

`DATABASE_URL` format for SQLAlchemy + psycopg:
`postgresql+psycopg://<user>:<password>@<pooler-host>:5432/postgres?sslmode=require`

## 2. VM setup (Ubuntu 24.04, Ampere A1, 1 OCPU / 6 GB)

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git rclone
sudo usermod -aG docker "$USER"   # log out and in again
sudo git clone https://github.com/sanjaysurya10/Dockcast.git /opt/dockcast
sudo mkdir -p /var/lib/dockcast/data && sudo chown 10001:10001 /var/lib/dockcast/data
sudo cp /opt/dockcast/.env.example /opt/dockcast/deploy/oracle/.env   # then edit DATABASE_URL
sudo chmod 600 /opt/dockcast/deploy/oracle/.env
```

## 3. Schema and start

```bash
cd /opt/dockcast
docker compose -f deploy/oracle/docker-compose.worker.yml --env-file deploy/oracle/.env \
  run --rm collector alembic upgrade head
docker compose -f deploy/oracle/docker-compose.worker.yml --env-file deploy/oracle/.env \
  up -d --build
docker compose -f deploy/oracle/docker-compose.worker.yml logs --tail 20 collector
```

## 4. Nightly archive (R2)

```bash
rclone config   # new remote "r2", type s3, provider Cloudflare, R2 token + account endpoint
sudo cp deploy/oracle/dockcast-archive.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now dockcast-archive.timer
```

`archive.sh` exports live rows older than `retention.raw_live_days` (7) to Parquet, uploads with
`rclone copy --checksum`, then prunes; prune refuses any day whose Parquet row count differs
from the database.

## 5. Checks

- `make health` with `DATABASE_URL` pointing at Supabase: uptime over the last 24 h (≥ 95%).
- GitHub → Actions → *collector-fallback*: runs every 5 min; it logs `primary_healthy_skip`
  while the VM is polling.
