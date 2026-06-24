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
14. [Production Hardening Checklist](#production-hardening-checklist)
15. [Stopping & Cleanup](#stopping--cleanup)

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
| All DataHub services | `quickstart` | Only coordinated tag available across all images |
| `datahub-actions` | `quickstart-locked` | The `quickstart` tag has a broken/corrupted venv (59 broken packages including `prometheus_client`, `tenacity`, `joserfc`). `quickstart-locked` is the stable pinned version |
| Frontend | `datahub-frontend-custom:latest` | Our custom build |
| Actions | `datahub-actions-custom:latest` | Our custom build |

### Important: `quickstart-locked` for actions only

The `quickstart-locked` tag only exists for `acryldata/datahub-actions`. All other services (`datahub-gms`, `datahub-upgrade`, etc.) use `quickstart`. This is why `DATAHUB_VERSION=quickstart` in `.env` and the override explicitly sets `datahub-actions-custom:latest`.

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

1. Check breaking changes: https://docs.datahub.com/docs/how/updating-datahub
2. Pull the new base compose file
3. Rebuild both custom images with the new base
4. Restart with `-v` to wipe volumes (only if schema migration requires it)

```bash
# Pull new base compose
curl -L "https://raw.githubusercontent.com/datahub-project/datahub/master/docker/quickstart/docker-compose.quickstart-profile.yml" \
  -o docker-compose.quickstart-base.yml

# Rebuild images
cd ~/datahub
docker build --no-cache -f docker/datahub-frontend/Dockerfile.custom -t datahub-frontend-custom:latest .
docker build --no-cache -f docker/datahub-actions/Dockerfile.custom -t datahub-actions-custom:latest .

# Restart
cd ~/datahub/datahub-deployment
docker compose -f docker-compose.quickstart-base.yml -f docker-compose.override.yml --profile quickstart down --remove-orphans -v
docker compose -f docker-compose.quickstart-base.yml -f docker-compose.override.yml --profile quickstart up -d
```

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