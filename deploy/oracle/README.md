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
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
# rclone: Ubuntu's package (v1.60) gets 501 NotImplemented from R2 on first upload; use the
# official build (checksum-verified), e.g. v1.75.2 for arm64 from https://downloads.rclone.org/
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
rclone lsf r2:dockcast-archive   # bucket-scoped token: list objects, not buckets
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

## 7. Forecast job (M5)

On the research machine, train the production bundle (`make train`, writes
`data/models/<bundle_id>/` and an MLflow `train` run), then copy it to the VM and start the job:

```bash
# research machine (from data/models)
tar czf - <bundle_id> | ssh ubuntu@<public-ip>   'sudo tar xzf - -C /var/lib/dockcast/data/models && sudo chown -R 10001:10001 /var/lib/dockcast/data/models'
# VM
$C run --rm --no-deps -v /opt/dockcast/data/reference:/app/data/reference:ro   weather-forecast python -m dockcast.ingest.calendar      # calendar_days (once, and after terms.csv edits)
$C up -d --build forecast
$C logs --tail 5 forecast       # expect: forecast_written issued_at=... rows=342 every 15 min (+60 s)
```

The job loads the newest bundle in `/var/lib/dockcast/data/models`, marks it champion in
`model_versions`, and skips a cycle when the newest live row is older than 30 min. Stations not
in the bundle's training set get no forecast until the next retrain.

## 7a. Update to M15 (forecast drivers)

M15 adds migration `0007` (`forecast_drivers`). The forecast job now also writes the TreeSHAP
feature-group drivers of each forecast, keeping only the latest issue (about 2,000 rows).

```bash
cd /opt/dockcast && git pull
$C build
$C run --rm collector alembic upgrade head      # expect: Running upgrade 0006 -> 0007
$C up -d forecast
$C logs --tail 5 forecast       # expect: forecast_written ... rows=342 drivers=2052
```

## 7b. Public API over HTTPS (M17)

The API runs on this VM next to the collector, behind Caddy, which gets and renews a free
Let's Encrypt certificate. No domain is needed: `sslip.io` resolves `<ip-with-dashes>.sslip.io`
to that IP (owner decision 2026-11-01).

1. **Hostname.** With the VM's public IP, e.g. `203.0.113.7`, the host is `203-0-113-7.sslip.io`.
2. **Oracle firewall.** Console → *Networking → Virtual cloud networks* → the VM's VCN → its
   subnet's *Security list* → *Add ingress rules*: source `0.0.0.0/0`, TCP, destination port
   `80`, and again for `443`.
3. **VM firewall.** Oracle's Ubuntu images reject new inbound traffic with an iptables rule.
   Insert the two ports above that rule and save:

   ```bash
   sudo iptables -L INPUT --line-numbers          # note the line number N of the REJECT rule
   sudo iptables -I INPUT N -p tcp -m state --state NEW --dport 80 -j ACCEPT
   sudo iptables -I INPUT N -p tcp -m state --state NEW --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```

4. **Settings.** Add to `deploy/oracle/.env` (the frontend origin comes from section 7c; use a
   placeholder until then):

   ```
   API_HOST=203-0-113-7.sslip.io
   API_CORS_ORIGINS=https://dockcast.pages.dev
   ```

5. **Start.**

   ```bash
   cd /opt/dockcast && git pull
   $C build
   $C run --rm collector alembic upgrade head      # 0007 if section 7a was skipped
   $C up -d                                        # api and caddy join the workers
   curl -s https://203-0-113-7.sslip.io/health     # expect "status":"ok" and a valid certificate
   ```

`GET /health` says `"status":"degraded"` (still HTTP 200) when the collector or forecast job is
more than 30 min behind; the uptime monitor below watches for that text.

## 7c. Frontend on Cloudflare Pages (M17)

Cloudflare dashboard → *Workers & Pages* → *Create* → *Pages* → *Connect to Git* → the
`Dockcast` repository, then:

| Setting | Value |
|---|---|
| Production branch | `main` |
| Root directory | `web` |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Environment variable | `VITE_API_BASE` = `https://203-0-113-7.sslip.io` |

Node 24 comes from `web/.nvmrc`. Pages rebuilds on every push to `main`. Without a `404.html`,
Pages serves `index.html` for unknown paths, so deep links like `/station/5` work. Put the
`*.pages.dev` URL in `API_CORS_ORIGINS` (section 7b) and run `$C up -d api`.

## 7d. Uptime monitor (M17)

UptimeRobot (free plan: 50 monitors, 5-min checks, keyword monitors included):
*New monitor* → type **Keyword** → URL `https://203-0-113-7.sslip.io/health` → keyword
`"status":"ok"` → alert when the keyword **does not exist** → interval 5 min → your email as
the alert contact. This catches the API, the database, the collector and the forecast job.

## 7e. Publish backtest results (M17)

The model page reads backtest rows from the hosted database; they are computed on the research
machine. From the repository on the research machine (local Postgres running), with the hosted
URL from section 1.3 in your shell only:

```bash
make publish-backtest ARGS=--dry-run            # lists E1/E2/E4/E7 runs, writes nothing
PUBLISH_DATABASE_URL='postgresql+psycopg://...' make publish-backtest
```

About 62,000 rows (≈ 18 MB). Re-running replaces the same runs. The error-analysis JSON ships
inside the API image.

## 7f. Retention of forecasts

The nightly archive (section 5) now also exports forecasts issued more than 14 days ago to
`r2:dockcast-archive/forecasts/date=YYYY-MM-DD/` and then deletes them from the hosted database,
with the same row-count check as the raw rows.

## 8. Checks

```bash
$C run --rm collector python -m dockcast.quality.health   # last 24 h uptime, target >= 95%
```

Once the VM collector is running, stop the local PC collector (`make collector-down`) so the feed
is polled once per minute only (PRD 21).
