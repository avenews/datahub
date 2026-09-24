# Avenews DataHub — Docker Deployment Guide

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Repository Structure](#repository-structure)
3. [Prerequisites](#prerequisites)
4. [First-Time Setup](#first-time-setup)
5. [Starting the Stack](#starting-the-stack)
6. [Custom Frontend (FE)](#custom-frontend-fe)
7. [Custom Ingestion Sources](#custom-ingestion-sources)
8. [Adding New Custom Sources in Future](#adding-new-custom-sources-in-future)
9. [Image Version Notes](#image-version-notes)
10. [Secrets Management](#secrets-management)
11. [Health Checks & Troubleshooting](#health-checks--troubleshooting)
12. [Backup & Restore](#backup--restore)
13. [Upgrading DataHub](#upgrading-datahub)
14. [Upgrade Summary](#upgrade-summary)
15. [Production Hardening Checklist](#production-hardening-checklist)
16. [Stopping & Cleanup](#stopping--cleanup)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND (FE)                              │
│         datahub-frontend-custom:latest  :9002                   │
│   Play 3 / Apache Pekko — React assets baked into JAR           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP proxy
┌───────────────────────────▼─────────────────────────────────────┐
│                      BACKEND (BE)                               │
│                                                                 │
│   datahub-gms :8080  ◄──►  datahub-actions-custom:latest        │
│                      ◄──►  system-update (one-shot job)         │
└──┬────────────┬────────────┬────────────────────────────────────┘
   │            │            │
   ▼            ▼            ▼
MySQL:3306  OpenSearch:9200  Kafka + Zookeeper
```

**Key design decisions:**
- **No Neo4j** — OpenSearch used as graph backend (simpler, less RAM)
- **No Kubernetes** — pure Docker Compose deployment
- **Two custom images** — `datahub-frontend-custom` and `datahub-actions-custom`
- **Base + Override pattern** — official quickstart base file never modified; all customisations in `docker-compose.override.yml`

---

## Repository Structure

```
datahub-deployment/
├── docker-compose.quickstart-base.yml   # Official DataHub base — DO NOT EDIT
├── docker-compose.override.yml          # Our customisations layered on top
├── .env                                 # Secrets & config — NEVER commit to git
├── .env.example                         # Template for .env
├── .gitignore                           # Ensures .env is never committed
└── README.md                            # This file

datahub/
├── docker/
│   ├── datahub-frontend/
│   │   └── Dockerfile.custom            # Custom FE image build
│   └── datahub-actions/
│       └── Dockerfile.custom            # Custom actions image build
├── datahub-web-react/                   # React frontend source (modified)
│   ├── src/                             # Custom components, themes, auth
│   └── dist/                            # Built React assets (run yarn build first)
└── metadata-ingestion/
    └── src/datahub/ingestion/source/
        ├── zoho_crm/                    # Custom Zoho CRM source
        ├── zoho_books/                  # Custom Zoho Books source
        └── posthog/                     # Custom PostHog source
```

---

## Prerequisites

- Docker Engine ≥ 20.x and Docker Compose ≥ 2.20
- WSL2 (Windows) or Linux/macOS
- 16 GB RAM minimum, 4 CPU cores, 50 GB disk
- Node.js + Yarn (for rebuilding the React frontend)
- Python 3.10+ (for rebuilding the ingestion wheel)

---

## First-Time Setup

### 1. Download the official base compose file

```bash
cd ~/datahub/datahub-deployment

curl -L "https://raw.githubusercontent.com/datahub-project/datahub/master/docker/quickstart/docker-compose.quickstart-profile.yml" \
  -o docker-compose.quickstart-base.yml
```

### 2. Create your .env file

```bash
cp .env.example .env
```

Edit `.env` and fill in all `CHANGEME` values. Generate secrets with:

```bash
openssl rand -base64 32   # run 3 times for DATAHUB_SECRET, TOKEN_SIGNING_KEY, TOKEN_SALT
```

### 3. Build the custom frontend image

```bash
# Step 1: Build the React app
cd ~/datahub/datahub-web-react
yarn install
yarn build

# Step 2: Build the Docker image (from repo root)
cd ~/datahub
docker build \
  -f docker/datahub-frontend/Dockerfile.custom \
  -t datahub-frontend-custom:latest \
  .
```

### 4. Build the custom actions image

```bash
cd ~/datahub
docker build \
  -f docker/datahub-actions/Dockerfile.custom \
  -t datahub-actions-custom:latest \
  .
```

### 5. Create the plugins directory

```bash
mkdir -p ~/.datahub/plugins
```

---

## Starting the Stack

Always use both files together:

```bash
cd ~/datahub/datahub-deployment

docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  up -d
```

Check everything is healthy:

```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

The UI is available at **http://localhost:9002**
Default login: `datahub` / `datahub` — **change this immediately**.

Watch logs:
```bash
docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  logs -f
```

---

## Custom Frontend (FE)

### How it works

The DataHub frontend is a Play 3 / Apache Pekko application. The React app is **not** served as loose files — it is bundled inside a JAR file (`datahub-web-react-*-assets.jar`) that lives in `/datahub-frontend/lib/`. Play loads it from the classpath at startup.

Our `Dockerfile.custom` for the frontend:
1. Starts from the official `acryldata/datahub-frontend-react:quickstart` image
2. Unpacks the React assets JAR
3. Replaces the `public/` directory with our freshly built `dist/`
4. Repacks the JAR with the **exact original filename** (required — Play's startup script hardcodes the classpath)

### Rebuilding after frontend changes

```bash
# 1. Make your changes in datahub-web-react/src/

# 2. Build the React app
cd ~/datahub/datahub-web-react
yarn build

# 3. Rebuild the Docker image
cd ~/datahub
docker build \
  --no-cache \
  -f docker/datahub-frontend/Dockerfile.custom \
  -t datahub-frontend-custom:latest \
  .

# 4. Restart just the frontend container
cd ~/datahub/datahub-deployment
docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  up -d --no-deps frontend-quickstart
```

### What we customised

| File | Change |
|------|--------|
| `datahub-web-react/src/app/auth/shared/AuthPageContainer.tsx` | Custom auth page |
| `datahub-web-react/src/app/homeV2/layout/navBarRedesign/NavBarHeader.tsx` | Custom nav bar |
| `datahub-web-react/src/app/ingest/source/builder/sources.json` | Custom ingestion sources |
| `datahub-web-react/src/app/ingestV2/source/builder/sources.json` | Custom ingestion sources V2 |
| `datahub-web-react/src/conf/theme/colorThemes/color.ts` | Custom colour palette |
| `datahub-web-react/src/conf/theme/colorThemes/light.ts` | Custom light theme |
| `datahub-web-react/src/conf/theme/themeV2.ts` | Custom theme V2 |
| `datahub-web-react/public/assets/logos/` | Avenews logo files |
| `datahub-web-react/.env` | Frontend environment config |
| `datahub-frontend/app/controllers/AuthenticationController.java` | Custom auth controller |

---

## Custom Ingestion Sources

We have three custom ingestion sources built directly into `metadata-ingestion`:

| Source | Type key | Location |
|--------|----------|----------|
| Zoho CRM | `zoho-crm` | `metadata-ingestion/src/datahub/ingestion/source/zoho_crm/` |
| Zoho Books | `zoho-books` | `metadata-ingestion/src/datahub/ingestion/source/zoho_books/` |
| PostHog | `posthog` | `metadata-ingestion/src/datahub/ingestion/source/posthog/` |

### How the executor works

When you trigger ingestion from the UI, the `datahub-actions` container receives the request via Kafka and runs it. The executor supports two venv modes:

- **Dynamic venv** (default) — downloads `acryl-datahub` from PyPI and installs the plugin. Only works for official built-in sources.
- **Bundled venv** — uses a pre-built venv baked into the Docker image at `/opt/datahub/venvs/<plugin>-bundled`. Required for custom sources.

### How our custom actions image works

Our `Dockerfile.custom` for actions:
1. Starts from `acryldata/datahub-actions:quickstart-locked` (the stable locked tag — `quickstart` is broken)
2. Copies our custom source files into `/metadata-ingestion/src/datahub/ingestion/source/`
3. Patches `/opt/datahub/venvs/common-venv/lib/python3.11/site-packages/acryl_datahub-*.dist-info/entry_points.txt` — inserting our sources under `[datahub.ingestion.source.plugins]` using `sed` (appending doesn't work as it puts them in the wrong section)
4. Creates `zoho-crm-bundled`, `zoho-books-bundled`, and `posthog-bundled` directories with symlinks to `common-venv/bin/python`, `python3`, and `datahub`

### Running a custom ingestion source

1. Go to **Ingestion** in the DataHub UI
2. Create or edit your ingestion source (e.g. Zoho CRM)
3. In **Advanced Settings**, set **CLI Version** to `bundled`
4. Save and Run

The `bundled` CLI version tells the executor to use `/opt/datahub/venvs/zoho-crm-bundled` which points to the `common-venv` where our sources are registered.

---

## Adding New Custom Sources in Future

Follow these steps to add a new custom ingestion source:

### Step 1: Write the source

Create a new directory under `metadata-ingestion/src/datahub/ingestion/source/your_source/`:
- `__init__.py`
- `your_source_config.py` — Pydantic config model
- `your_source_source.py` — Source class implementing `Source`

### Step 2: Register in setup.py

In `metadata-ingestion/setup.py`, add to the `entry_points` under `datahub.ingestion.source.plugins`:

```python
"your-source = datahub.ingestion.source.your_source.your_source_source:YourSource",
```

### Step 3: Add to sources.json for the UI

In `datahub-web-react/src/app/ingestV2/source/builder/sources.json`, add an entry:

```json
{
  "urn": "urn:li:dataPlatform:your-source",
  "name": "Your Source",
  "displayName": "Your Source",
  "recipe": "source:\n  type: your-source\n  config:\n    ...",
  "logoUrl": "/assets/logos/your-source-logo.png"
}
```

Add the logo image to `datahub-web-react/public/assets/logos/`.

### Step 4: Rebuild the actions image

```bash
cd ~/datahub
docker build \
  --no-cache \
  -f docker/datahub-actions/Dockerfile.custom \
  -t datahub-actions-custom:latest \
  .
```

Update `Dockerfile.custom` to add the COPY and the new entry in the `sed` command:

```dockerfile
COPY metadata-ingestion/src/datahub/ingestion/source/your_source/ \
     /metadata-ingestion/src/datahub/ingestion/source/your_source/
```

Add to the `sed` command:
```dockerfile
RUN EP_FILE="..." && \
    sed -i '/^\[datahub\.ingestion\.source\.plugins\]/a \
    your-source = datahub.ingestion.source.your_source.your_source_source:YourSource\n...' "$EP_FILE"
```

Add to the bundled venvs loop:
```dockerfile
RUN for plugin in zoho-crm zoho-books posthog your-source; do \
    ...
```

### Step 5: Rebuild the frontend image

```bash
cd ~/datahub/datahub-web-react
yarn build

cd ~/datahub
docker build \
  --no-cache \
  -f docker/datahub-frontend/Dockerfile.custom \
  -t datahub-frontend-custom:latest \
  .
```

### Step 6: Restart

```bash
cd ~/datahub/datahub-deployment

docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  down --remove-orphans -v

docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  up -d
```

---

## Image Version Notes

### Why we use specific tags

| Image | Tag used | Reason |
|-------|----------|--------|
| DataHub services | `${DATAHUB_VERSION}` | Pin every release to one coordinated DataHub tag |
| `datahub-actions` | `quickstart-locked` | The `quickstart` tag has a broken/corrupted venv (59 broken packages including `prometheus_client`, `tenacity`, `joserfc`). `quickstart-locked` is the stable pinned version |
| Frontend | `datahub-frontend-custom:${DATAHUB_FRONTEND_VERSION}` | Custom React assets built against the selected DataHub release |
| Actions | `datahub-actions-custom:latest` | Our custom build |

### Important: `quickstart-locked` for actions only

The `quickstart-locked` tag is used only as the base for the custom actions image. The GMS and system-update images use the exact value of `DATAHUB_VERSION`. The custom frontend image must use the same release in `DATAHUB_FRONTEND_VERSION`.

---

## Secrets Management

All secrets live in `.env` which is gitignored. Never hardcode secrets in `docker-compose.override.yml` or any committed file.

```bash
# Generate secrets
openssl rand -base64 32  # DATAHUB_SECRET (must be 32+ chars for Play 3)
openssl rand -base64 32  # DATAHUB_TOKEN_SERVICE_SIGNING_KEY
openssl rand -base64 32  # DATAHUB_TOKEN_SERVICE_SALT
```

The `MYSQL_ROOT_PASSWORD` must be set to `datahub` (matching the base compose file) — the `system-update` job connects as root using this password to run schema migrations.

---

## Health Checks & Troubleshooting

```bash
# Check all containers
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"

# GMS health
curl http://localhost:8080/health

# Check actions container logs
docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  logs datahub-actions-quickstart 2>&1 | tail -30

# Verify custom sources are registered in the actions container
docker exec datahub-datahub-actions-quickstart-1 \
  /opt/datahub/venvs/common-venv/bin/python3 -c \
  "import importlib.metadata; \
   eps = importlib.metadata.entry_points(group='datahub.ingestion.source.plugins'); \
   print([e.name for e in eps if 'zoho' in e.name or 'posthog' in e.name])"

# Verify custom FE is serving
curl -s http://localhost:9002 | grep title
```

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Ingestion stuck on "loading" | Actions container crashed | Check actions logs, ensure `datahub-actions-custom:latest` is used |
| `Failed to find registered source for zoho-crm` | CLI Version not set to `bundled` | Set CLI Version to `bundled` in Advanced Settings |
| `Server default CLI version is ahead of CLI version` | Bundled actions venv reports an older Docker build version | Rebuild `datahub-actions-custom:latest` with `acryl-datahub==1.7.0.9`, recreate `datahub-actions-quickstart`, and keep custom sources on CLI Version `bundled` |
| `Invalid version format` in a custom ingestion run | The ingestion CLI and GMS release are not aligned | Verify the bundled CLI reports `1.7.0.9`; do not override custom-source runs with an older or commit-hash CLI version |
| `Bundled startup venv not found` | Custom actions image not used | Ensure override sets `datahub-actions-quickstart: image: datahub-actions-custom:latest` |
| Frontend shows default DataHub | Old image cached | Hard refresh browser, or `docker compose up -d --no-deps frontend-quickstart` |
| `MYSQL_ROOT_PASSWORD access denied` | Root password mismatch | Set `MYSQL_ROOT_PASSWORD=datahub` in `.env` |
| Actions `ImportError: prometheus_client` | Using `quickstart` tag for actions | Use `quickstart-locked` base in `Dockerfile.custom` |

---

## Backup & Restore

```bash
# Backup MySQL
docker exec datahub-mysql-1 \
  mysqldump -u root --password=datahub datahub \
  > backup-$(date +%Y%m%d).sql

# Restore MySQL (stack must be running)
docker exec -i datahub-mysql-1 \
  mysql -u root --password=datahub datahub \
  < backup-YYYYMMDD.sql
```

---

## Upgrading DataHub

Use a release tag, not `master`, for a repeatable upgrade. Create a branch when the
compose or Dockerfile changes are being committed:

```bash
cd ~/datahub
git switch -c chore/datahub-upgrade-v1.7.0.1
```

For upgrades from a version older than `v1.7.0`, follow the release notes and upgrade
through `v1.6.0` first. Do not skip a required intermediate release.

### 1. Select and back up the release

```bash
cd ~/datahub/datahub-deployment

export DATAHUB_VERSION=v1.7.0.1
export COMPOSE="docker compose --env-file .env -f docker-compose.quickstart-base.yml -f docker-compose.override.yml --profile quickstart"

mkdir -p backups
$COMPOSE exec -T mysql mysqldump \
  -u root --password=datahub datahub \
  > "backups/datahub-before-${DATAHUB_VERSION}-$(date +%Y%m%d-%H%M%S).sql"
```

Set these matching values in `.env`:

```env
DATAHUB_VERSION=v1.7.0.1
DATAHUB_FRONTEND_IMAGE=datahub-frontend-custom
DATAHUB_FRONTEND_VERSION=v1.7.0.1
UI_INGESTION_DEFAULT_CLI_VERSION=1.7.0.9
```

Keep `.env` uncommitted. Generate `DATAHUB_SYSTEM_CLIENT_SECRET` if it is not
already present; system-update requires it in v1.7.0.1.

### 2. Download the pinned compose file

```bash
cp docker-compose.quickstart-base.yml \
  "docker-compose.quickstart-base.before-${DATAHUB_VERSION}.yml"

curl -fL \
  "https://raw.githubusercontent.com/datahub-project/datahub/${DATAHUB_VERSION}/docker/quickstart/docker-compose.quickstart-profile.yml" \
  -o docker-compose.quickstart-base.yml
```

### 3. Rebuild custom images

Build the React assets and frontend image with the same release tag:

```bash
cd ~/datahub/datahub-web-react
yarn build

cd ~/datahub
docker build --no-cache \
  -f docker/datahub-frontend/Dockerfile.custom \
  -t datahub-frontend-custom:${DATAHUB_VERSION} .
```

Build the actions image. Its Dockerfile pins the bundled CLI to `1.7.0.9` and
registers the custom sources in the bundled environment:

```bash
docker build --no-cache \
  -f docker/datahub-actions/Dockerfile.custom \
  -t datahub-actions-custom:latest .
```

### 4. Validate tags before restarting

```bash
cd ~/datahub/datahub-deployment
$COMPOSE config --images
```

Confirm that the output includes:

```text
acryldata/datahub-gms:v1.7.0.1
acryldata/datahub-upgrade:v1.7.0.1
datahub-frontend-custom:v1.7.0.1
datahub-actions-custom:latest
```

### 5. Restart without deleting data

```bash
$COMPOSE down --remove-orphans
$COMPOSE up -d --remove-orphans
```

Never add `-v` during a normal upgrade. It deletes the MySQL and OpenSearch
volumes and turns the operation into a fresh installation.

### 6. Verify the upgrade and custom sources

```bash
$COMPOSE ps
$COMPOSE logs --tail=200 system-update-quickstart

docker exec datahub-datahub-actions-quickstart-1 \
  /opt/datahub/venvs/common-venv/bin/python3 -c \
  "import importlib.metadata as m; print(m.version('acryl-datahub'))"

docker exec datahub-datahub-actions-quickstart-1 \
  /opt/datahub/venvs/common-venv/bin/python3 -c \
  "from datahub.ingestion.source.zoho_crm.zoho_crm_source import ZohoCRMSource; print(ZohoCRMSource.__name__)"
```

The migration should exit `0`, the bundled CLI should report `1.7.0.9`, and
custom ingestion sources must use CLI Version `bundled` in the UI.

### Rollback boundary

Restore the previous compose file and image tags only if the containers fail to
start. Database and search migrations are not generally reversible; use the
MySQL backup and the previous DataHub release’s documented restore procedure
before attempting a data rollback.

## Upgrade Summary

The `v1.7.0.1` upgrade added the following compatibility and operational changes:

- Pinned the GMS, system-update, and frontend images to `v1.7.0.1`.
- Updated the custom frontend Dockerfile to use the v1.7.0.1 base image and discover asset JAR names dynamically.
- Removed unsupported `lineageGraphV2` and `lineageGraphV3` fields from the frontend app-config query so the navigation can finish loading against the v1.7.0.1 GraphQL schema.
- Added `DATAHUB_SYSTEM_CLIENT_SECRET` wiring for frontend, GMS, actions, and system-update.
- Updated custom connector support statuses from removed `INCUBATING` to `BETA`.
- Pinned the bundled actions CLI to `acryl-datahub==1.7.0.9` and kept custom Zoho CRM, Zoho Books, and PostHog sources registered in that environment.
- Kept entity versioning enabled through `ENTITY_VERSIONING_ENABLED=true`.

---

## Production Hardening Checklist

- [ ] All secrets in `.env` are unique and ≥32 chars
- [ ] `.env` is in `.gitignore` and never committed
- [ ] `MYSQL_ROOT_PASSWORD=datahub` (required by system-update)
- [ ] `METADATA_SERVICE_AUTH_ENABLED=true` in override
- [ ] Default `datahub/datahub` credentials changed after first login
- [ ] Reverse proxy (nginx/Caddy/Traefik) in front of port 9002 with TLS
- [ ] `UI_INGESTION_DEFAULT_CLI_VERSION=1.6.0` set in `.env`
- [ ] Custom actions image used (`datahub-actions-custom:latest`)
- [ ] Custom frontend image used (`datahub-frontend-custom:latest`)
- [ ] All custom ingestion sources tested with CLI Version `bundled`
- [ ] Regular MySQL backups scheduled
- [ ] `.gitignore` includes `.env` and `*.sql`

---

## Stopping & Cleanup

```bash
# Stop without removing data
docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  down --remove-orphans

# Stop and remove all volumes — DESTRUCTIVE, deletes all metadata
docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  down --remove-orphans -v

# Remove unused images to free disk space
docker image prune -f
```

---

## DevOps Quickstart — Separating FE and BE

This section is for DevOps engineers deploying or maintaining the Avenews DataHub stack.

### Two Custom Images to Build

Everything starts with building two custom Docker images. These must be rebuilt whenever source code changes.

**Frontend Image (`datahub-frontend-custom`)**
```bash
# 1. Build the React app first (required before building the image)
cd ~/datahub/datahub-web-react
yarn install
yarn build

# 2. Build the Docker image from repo root
cd ~/datahub
docker build \
  --no-cache \
  -f docker/datahub-frontend/Dockerfile.custom \
  -t datahub-frontend-custom:latest \
  .
```

**Actions Image (`datahub-actions-custom`)**
```bash
cd ~/datahub
docker build \
  --no-cache \
  -f docker/datahub-actions/Dockerfile.custom \
  -t datahub-actions-custom:latest \
  .
```

---

### FE Container

| Property | Value |
|----------|-------|
| Service name | `frontend-quickstart` |
| Image | `datahub-frontend-custom:latest` |
| Port | `9002` |
| Health check | `GET /admin` |
| Depends on | `datahub-gms-quickstart` (BE) |

The FE container is a Play 3 / Apache Pekko application. It serves the React app and proxies API calls to GMS.

**Environment variables required:**
```
DATAHUB_GMS_HOST=datahub-gms
DATAHUB_GMS_PORT=8080
DATAHUB_SECRET=<32+ char secret>
DATAHUB_TOKEN_SERVICE_SIGNING_KEY=<32+ char secret>
DATAHUB_TOKEN_SERVICE_SALT=<32+ char secret>
```

**To restart FE only (zero downtime for BE):**
```bash
cd ~/datahub/datahub-deployment

docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  up -d --no-deps frontend-quickstart
```

---

### BE Containers

The backend consists of these services:

| Service | Image | Role |
|---------|-------|------|
| `datahub-gms-quickstart` | `acryldata/datahub-gms:quickstart` | Core metadata API (GraphQL + REST) |
| `datahub-actions-quickstart` | `datahub-actions-custom:latest` | Ingestion executor + event processor |
| `system-update-quickstart` | `acryldata/datahub-upgrade:quickstart` | One-shot schema migration (runs on startup) |
| `mysql` | `mysql:8.2` | Primary metadata store |
| `opensearch` | `opensearchproject/opensearch:2.19.3` | Search + graph backend |
| `kafka-broker` | `confluentinc/cp-kafka:8.0.0` | Event streaming |

**GMS environment variables required:**
```
DATAHUB_SECRET=<same as FE>
DATAHUB_TOKEN_SERVICE_SIGNING_KEY=<same as FE>
DATAHUB_TOKEN_SERVICE_SALT=<same as FE>
METADATA_SERVICE_AUTH_ENABLED=true
MYSQL_PASSWORD=<db password>
MYSQL_ROOT_PASSWORD=datahub  ← must be 'datahub', used by system-update
```

**To restart BE only (keeps FE running):**
```bash
cd ~/datahub/datahub-deployment

docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  up -d --no-deps datahub-gms-quickstart
```

---

### Always Use Both Compose Files

Every `docker compose` command must reference both files and the profile:

```bash
docker compose \
  -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml \
  --profile quickstart \
  <command>
```

The base file (`docker-compose.quickstart-base.yml`) is the official DataHub compose — never edit it. The override file (`docker-compose.override.yml`) contains all Avenews customisations and is merged on top.

---

### Deploying Updates

**FE-only update** (e.g. UI changes, branding, new ingestion source UI):
```bash
# 1. Rebuild React app
cd ~/datahub/datahub-web-react && yarn build

# 2. Rebuild FE image
cd ~/datahub
docker build --no-cache \
  -f docker/datahub-frontend/Dockerfile.custom \
  -t datahub-frontend-custom:latest .

# 3. Restart FE container only — BE stays up
cd ~/datahub/datahub-deployment
docker compose -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml --profile quickstart \
  up -d --no-deps frontend-quickstart
```

**Actions-only update** (e.g. new custom ingestion source):
```bash
# 1. Rebuild actions image
cd ~/datahub
docker build --no-cache \
  -f docker/datahub-actions/Dockerfile.custom \
  -t datahub-actions-custom:latest .

# 2. Restart actions container only
cd ~/datahub/datahub-deployment
docker compose -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml --profile quickstart \
  up -d --no-deps datahub-actions-quickstart
```

**Full stack update** (e.g. DataHub version bump):
```bash
cd ~/datahub/datahub-deployment

# Bring everything down (use -v only if schema migration requires it)
docker compose -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml --profile quickstart \
  down --remove-orphans

# Bring everything back up
docker compose -f docker-compose.quickstart-base.yml \
  -f docker-compose.override.yml --profile quickstart \
  up -d
```

---

### Custom Ingestion Sources — Important Notes

Three custom ingestion sources are bundled in `datahub-actions-custom`:

| Source | Type key | CLI Version setting |
|--------|----------|---------------------|
| Zoho CRM | `zoho-crm` | **Must be set to `bundled`** |
| Zoho Books | `zoho-books` | **Must be set to `bundled`** |
| PostHog | `posthog` | **Must be set to `bundled`** |
| All other sources | e.g. `mongodb` | Leave as default (`1.6.0.6rc2`) |

When creating ingestion sources for Zoho/PostHog in the UI:
1. Go to **Ingestion** → **Create Source**
2. Select the source type
3. Click **Advanced**
4. Set **CLI Version** to `bundled`
5. Save and Run

Standard sources (MongoDB, PostgreSQL, etc.) do NOT need `bundled` — they download dynamically from PyPI.

---

### Port Reference

| Service | Internal port | Exposed on host |
|---------|--------------|-----------------|
| Frontend UI | 9002 | `0.0.0.0:9002` |
| GMS API | 8080 | `127.0.0.1` only |
| MySQL | 3306 | `127.0.0.1` only |
| OpenSearch | 9200 | `127.0.0.1` only |
| Kafka | 9092 | `127.0.0.1` only |

Only port 9002 is publicly accessible. All other ports are bound to localhost. Put a reverse proxy (nginx/Caddy/Traefik) in front of 9002 for TLS termination in production.

---

### Quick Health Check

```bash
# All containers
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"

# GMS API
curl http://localhost:8080/health

# Frontend
curl -s http://localhost:9002 | grep title

# Actions container running
docker ps | grep actions
```