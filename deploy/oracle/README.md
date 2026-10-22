# Cloud collector (PRD 18.2)

Always-on worker on an Oracle Cloud Always Free VM, writing to a Supabase Postgres, nightly
Parquet archive to Cloudflare R2, and a GitHub Actions fallback every 5 min.
**The owner creates every account, key and secret; the builder never handles credentials.**

## 1. Supabase (database)

1. New project, region **West EU (Ireland)** if offered. Save the database password in your
   password manager.
2. **Turn off public API access to our tables.** When creating the project: untick *Enable Data
   API* and *Automatically expose new tables*, tick *Enable automatic RLS* (done 2026-10-22).
   DockCast only uses a direct Postgres connection.
3. *Connect* → **Session pooler** connection string (IPv4; the direct host is IPv6-only unless the
   paid IPv4 add-on is enabled, and Oracle VMs are IPv4 by default). For this project
   (`oyfrejzjkhjaohtknbvh`, eu-west-1) `DATABASE_URL` is:

   ```
   postgresql+psycopg://postgres.oyfrejzjkhjaohtknbvh:<PASSWORD>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require
   ```

   Replace `<PASSWORD>` with the database password, percent-encoding special characters
   (`@`→`%40`, `#`→`%23`, `/`→`%2F`, `:`→`%3A`, `?`→`%3F`, `&`→`%26`, `%`→`%25`).
4. Schema: already created (2026-10-22) from `alembic upgrade head --sql`, revision `0004`; all 15
   tables owned by `postgres` (bypasses RLS), automatic RLS on with no policies, so Data API roles
   are denied.

## 2. Cloudflare R2 (archive)

1. R2 → create bucket `dockcast-archive` (location hint: Western Europe).
2. R2 → *Manage API tokens* → create token: **Object Read & Write**, bucket `dockcast-archive`
   only. Note the Access Key ID, Secret Access Key and the S3 endpoint
   `https://<account-id>.r2.cloudflarestorage.com`.

## 3. Oracle Cloud VM (worker)

1. Compute → Instances → Create: image **Ubuntu 24.04**, shape **VM.Standard.A1.Flex** with
   1 OCPU / 6 GB (Always Free eligible). Add your SSH public key. If you see "Out of capacity",
   retry later or pick another availability domain.
2. Optional, recommended: upgrade the account to Pay-As-You-Go (no charge inside Always Free
   limits; reportedly avoids idle reclamation — a collector is mostly idle).
3. SSH in (`ssh ubuntu@<public-ip>`) and run:

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git rclone
sudo usermod -aG docker "$USER" && exit          # log in again afterwards
sudo git clone https://github.com/sanjaysurya10/Dockcast.git /opt/dockcast
sudo chown -R "$USER" /opt/dockcast
sudo mkdir -p /var/lib/dockcast/data && sudo chown 10001:10001 /var/lib/dockcast/data
cd /opt/dockcast
cp .env.example deploy/oracle/.env && chmod 600 deploy/oracle/.env
nano deploy/oracle/.env     # set DATABASE_URL (from step 1.3); optionally CONTACT_EMAIL
```

## 4. Create the schema and start the collector

```bash
cd /opt/dockcast
C="docker compose -f deploy/oracle/docker-compose.worker.yml --env-file deploy/oracle/.env"
$C build
$C run --rm collector alembic current           # expect: 0004 (head) — also proves the URL works
$C up -d
$C logs --tail 5 collector                      # expect: poll ... rows=115 status=ok
```

The container restarts on failure and after a VM reboot (Docker starts on boot).

## 5. Nightly archive to R2

```bash
rclone config    # n → name: r2 → Storage: s3 → provider: Cloudflare → access key / secret
                 # from step 2.2 → endpoint: https://<account-id>.r2.cloudflarestorage.com
rclone lsd r2:   # expect: dockcast-archive
sudo cp deploy/oracle/dockcast-archive.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now dockcast-archive.timer
systemctl list-timers dockcast-archive.timer
```

`archive.sh` (02:17 UTC) exports live rows older than `retention.raw_live_days` (7) to Parquet,
uploads with `rclone copy --checksum`, then prunes; prune refuses any day whose Parquet row count
differs from the database.

## 6. GitHub Actions fallback

GitHub → repository → *Settings → Secrets and variables → Actions* → new secret
`DATABASE_URL` = the same URL as step 1.3 (optional: `CONTACT_EMAIL`).
Workflow `collector-fallback` runs every 5 min and logs `primary_healthy_skip` while the VM polls.

## 7. Checks

```bash
$C run --rm collector python -m dockcast.quality.health   # last 24 h uptime, target >= 95%
```

Once the VM collector is running, stop the local PC collector (`make collector-down`) so the feed
is polled once per minute only (PRD 21).
