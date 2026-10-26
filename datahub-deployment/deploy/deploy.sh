#!/usr/bin/env bash
# Deploys DataHub on this host with Docker Compose. Run as root by the GitHub workflow through SSM Run Command.
#
#   deploy.sh --env <dev|prod> --region <aws-region> --bundle-dir <dir> --services <frontend|actions|gms|all|a,b> [--frontend-tag T] [--actions-tag T]
#
# The bundle directory holds this script, config/<env>.conf and the three compose files (the workflow uploads it to
# S3 and the host downloads it). Secrets are read from AWS Secrets Manager (datahub/<env>/app, mysql, oidc) with the
# instance role and written only to .env (mode 0600); they are never printed.
#
# Services: frontend, actions and gms update just those containers (--no-deps, so MySQL, Kafka and OpenSearch are
# left alone). gms and all also run the system-update job first. A failed frontend or actions deploy is rolled back
# to the previous image tag.
set -euo pipefail

ENVIRONMENT=""
REGION=""
BUNDLE_DIR=""
SERVICES=""
FRONTEND_TAG=""
ACTIONS_TAG=""

die() { echo "ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENVIRONMENT="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --bundle-dir) BUNDLE_DIR="$2"; shift 2 ;;
    --services) SERVICES="$2"; shift 2 ;;
    --frontend-tag) FRONTEND_TAG="$2"; shift 2 ;;
    --actions-tag) ACTIONS_TAG="$2"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$ENVIRONMENT" ] && [ -n "$REGION" ] && [ -n "$BUNDLE_DIR" ] && [ -n "$SERVICES" ] || die "--env, --region, --bundle-dir and --services are required"
[[ "$REGION" =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]] || die "invalid region: $REGION"
[[ "$ENVIRONMENT" =~ ^(dev|prod)$ ]] || die "environment must be dev or prod"
[[ "$SERVICES" =~ ^(all|(frontend|actions|gms)(,(frontend|actions|gms))*)$ ]] || die "services must be all or a comma list of frontend, actions, gms"
for t in "$FRONTEND_TAG" "$ACTIONS_TAG"; do
  [[ -z "$t" || "$t" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || die "invalid image tag: $t"
done

APP_USER="ubuntu"
APP_DIR="/home/$APP_USER/datahub/datahub-deployment"
STATE_DIR="/home/$APP_USER/datahub/state"
SECRET_PREFIX="datahub/$ENVIRONMENT"
COMPOSE_FILES=(docker-compose.quickstart-base.yml docker-compose.override.yml docker-compose.dev-host.yml)

# One deploy at a time.
exec 9>/var/lock/datahub-deploy.lock
flock -n 9 || die "another deploy is running on this host"

# --- tools: the Ubuntu AMI has no AWS CLI
if ! command -v aws >/dev/null 2>&1; then
  echo "Installing the AWS CLI"
  snap install aws-cli --classic >/dev/null
fi
command -v jq >/dev/null 2>&1 || { apt-get update -y >/dev/null && apt-get install -y jq >/dev/null; }

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

mkdir -p "$APP_DIR" "$STATE_DIR"
[ -f "$BUNDLE_DIR/config/$ENVIRONMENT.conf" ] || die "missing $BUNDLE_DIR/config/$ENVIRONMENT.conf"
for f in "${COMPOSE_FILES[@]}"; do [ -f "$BUNDLE_DIR/$f" ] || die "missing $BUNDLE_DIR/$f"; done

# --- image tags: keep what is deployed unless a new tag is given
TAGS_FILE="$STATE_DIR/tags.env"
CURRENT_FRONTEND_TAG=""; CURRENT_ACTIONS_TAG=""
if [ -f "$TAGS_FILE" ]; then
  CURRENT_FRONTEND_TAG="$(sed -n 's/^FRONTEND_TAG=//p' "$TAGS_FILE")"
  CURRENT_ACTIONS_TAG="$(sed -n 's/^ACTIONS_TAG=//p' "$TAGS_FILE")"
fi
NEW_FRONTEND_TAG="${FRONTEND_TAG:-$CURRENT_FRONTEND_TAG}"
NEW_ACTIONS_TAG="${ACTIONS_TAG:-$CURRENT_ACTIONS_TAG}"

wants() { [ "$SERVICES" = "all" ] || [[ ",$SERVICES," == *",$1,"* ]]; }
if wants frontend; then [ -n "$NEW_FRONTEND_TAG" ] || die "no frontend image tag (none deployed yet, pass --frontend-tag)"; fi
if wants actions;  then [ -n "$NEW_ACTIONS_TAG" ]  || die "no actions image tag (none deployed yet, pass --actions-tag)"; fi

# --- compose files
for f in "${COMPOSE_FILES[@]}"; do
  [ -f "$APP_DIR/$f" ] && cp -p "$APP_DIR/$f" "$STATE_DIR/$f.prev"
  install -m 0644 -o "$APP_USER" -g "$APP_USER" "$BUNDLE_DIR/$f" "$APP_DIR/$f"
done

# --- .env: plain config, image references, then the secrets. Values are single-quoted for Compose.
render_env() {  # frontend_tag actions_tag
  local out lines name
  out="$(mktemp)"; chmod 600 "$out"
  cat "$BUNDLE_DIR/config/$ENVIRONMENT.conf" > "$out"
  {
    echo "DATAHUB_FRONTEND_IMAGE=$REGISTRY/datahub-frontend-custom"
    echo "DATAHUB_FRONTEND_VERSION=$1"
    echo "DATAHUB_ACTIONS_IMAGE=$REGISTRY/datahub-actions-custom"
    echo "DATAHUB_ACTIONS_VERSION=$2"
  } >> "$out"
  for name in app mysql oidc; do
    # Each value is single-quoted for Compose; a missing, empty or REPLACE_ME value, or one with a quote, stops the deploy.
    lines="$(aws secretsmanager get-secret-value --secret-id "$SECRET_PREFIX/$name" --region "$REGION" \
        --query SecretString --output text \
      | jq -r --arg q "'" 'to_entries[] | if (.value|type)!="string" or (.value|contains($q)) or (.value|contains("\n")) or .value=="REPLACE_ME" or .value=="" then error("bad value for "+.key) else "\(.key)=\($q)\(.value)\($q)" end')" \
      || { rm -f "$out"; die "could not read secret $SECRET_PREFIX/$name (missing, empty, REPLACE_ME, or contains a quote)"; }
    printf '%s\n' "$lines" >> "$out"
  done
  chown "$APP_USER:$APP_USER" "$out"
  mv "$out" "$APP_DIR/.env"
}
render_env "${NEW_FRONTEND_TAG:-none}" "${NEW_ACTIONS_TAG:-none}"

# --- Docker: throwaway config for the ECR login
export DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null

compose() {
  local args=(--project-directory "$APP_DIR" -p datahub --profile quickstart)
  for f in "${COMPOSE_FILES[@]}"; do args+=(-f "$APP_DIR/$f"); done
  docker compose "${args[@]}" "$@"
}

service_names() {
  local names=()
  wants frontend && names+=(frontend-quickstart)
  wants actions  && names+=(datahub-actions-quickstart)
  wants gms      && names+=(datahub-gms-quickstart)
  echo "${names[@]}"
}

wait_http() {  # url seconds
  local url="$1" deadline=$((SECONDS + $2))
  until curl -fsS -o /dev/null --max-time 5 "$url"; do
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep 5
  done
}

check_health() {
  if wants gms;      then wait_http http://localhost:8080/health 300 || return 1; fi
  if wants frontend; then wait_http http://localhost:9002/ 180 || return 1; fi
  if wants actions;  then
    sleep 20
    [ "$(docker inspect -f '{{.State.Running}}' datahub-datahub-actions-quickstart-1 2>/dev/null)" = "true" ] || return 1
  fi
}

rollback() {
  echo "Health check failed; rolling back"
  if [ -n "$CURRENT_FRONTEND_TAG$CURRENT_ACTIONS_TAG" ]; then
    render_env "${CURRENT_FRONTEND_TAG:-none}" "${CURRENT_ACTIONS_TAG:-none}"
    local names=()
    wants frontend && [ -n "$CURRENT_FRONTEND_TAG" ] && names+=(frontend-quickstart)
    wants actions  && [ -n "$CURRENT_ACTIONS_TAG" ]  && names+=(datahub-actions-quickstart)
    if [ "${#names[@]}" -gt 0 ]; then compose up -d --no-deps "${names[@]}" || true; fi
  fi
  compose logs --tail 40 2>&1 | sed -E 's/(SECRET|PASSWORD|KEY|TOKEN)[A-Z_]*=.*/\1=***/' || true
}

# --- deploy
echo "Deploying: $SERVICES (frontend=${NEW_FRONTEND_TAG:-n/a} actions=${NEW_ACTIONS_TAG:-n/a})"
if [ "$SERVICES" = "all" ]; then
  compose pull --quiet
  compose up -d
else
  # shellcheck disable=SC2046
  compose pull --quiet $(service_names)
  if wants gms; then
    # gms depends on the system-update job, which in turn needs MySQL, Kafka and OpenSearch.
    # shellcheck disable=SC2046
    compose up -d $(service_names)
  else
    # shellcheck disable=SC2046
    compose up -d --no-deps $(service_names)
  fi
fi

if [ "$SERVICES" = "all" ]; then
  SERVICES="frontend,actions,gms"   # health-check everything that was started
fi
if check_health; then
  cat > "$TAGS_FILE" <<TAGS
FRONTEND_TAG=$NEW_FRONTEND_TAG
ACTIONS_TAG=$NEW_ACTIONS_TAG
TAGS
  echo "Deployed. Containers:"
  compose ps --format 'table {{.Name}}\t{{.Image}}\t{{.Status}}'
else
  rollback
  exit 1
fi
