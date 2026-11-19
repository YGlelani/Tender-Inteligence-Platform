#!/usr/bin/env bash
# Production deployment from this monorepo. Run by .github/workflows/deploy-production.yml
# on the production server's runner, only after the "production" environment approval and
# only when the repository variable PRODUCTION_DEPLOY_ENABLED is "true".
#
# It reuses each service's EXISTING production Compose file unchanged and writes the same
# .env files the per-service deploy workflows write today, so production keeps the same
# containers, ports, networks and volumes.
#
#   bash scripts/deploy/deploy_production.sh <service> [<service> ...]
#
# Services: tender-scrapping-database jwt signup-api notifications-api alerts-api tender-ml
#           tender-ai-agent tender-ai-frontend frontend
# Refused:  cache-api production runs ghcr.io/yglelani/lelani-cache-api, built elsewhere
#
# Compose project names. The production containers were created by the per-service
# workflows, whose project names come from their checkout folders, and Docker refuses to
# create a container whose fixed name belongs to another project. The defaults below are
# derived from those workflows; confirm them with `docker compose ls` on the server and
# override with the PROJECT_* variables if they differ.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_LOGIN_API="${PROJECT_LOGIN_API:-musiwalo-jwt-api}"
PROJECT_SIGNUP_API="${PROJECT_SIGNUP_API:-signup-api}"
PROJECT_NOTIFICATIONS_API="${PROJECT_NOTIFICATIONS_API:-tender_apis}"
PROJECT_ALERTS_API="${PROJECT_ALERTS_API:-deploy-src}"
PROJECT_TENDER_ML="${PROJECT_TENDER_ML:-deploy-src}"

require() {
    local missing=() name
    for name in "$@"; do
        [ -n "${!name:-}" ] || missing+=("$name")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "::error::Missing production secrets or variables: ${missing[*]}"
        exit 1
    fi
}

write_env() { # <dir> NAME=value ...  -> <dir>/.env readable by the runner user only
    local file="$1/.env"
    shift
    (
        umask 077
        : > "$file"
        local pair
        for pair in "$@"; do
            printf '%s\n' "$pair" >> "$file"
        done
    )
}

wait_for() { # <url> <container>
    local _
    for _ in $(seq 1 24); do
        if curl -fsS --max-time 10 "$1" > /dev/null 2>&1; then
            echo "OK $1"
            return 0
        fi
        sleep 5
    done
    echo "::error::$1 did not become healthy"
    docker logs --tail 100 "$2" || true
    return 1
}

deploy_tender_scrapping_database() {
    require SCRAPER_API_KEY AI_SERVICE_API_KEY ETENDERS_BASE_URL
    cd "$ROOT/tender-scrapping-database"
    # Project "tender-scrapping" (name: in compose.yaml). Services are listed so the
    # one-time sqlite-migrate job does not run; no --remove-orphans, so containers this
    # file no longer describes are left alone.
    API_KEY="$SCRAPER_API_KEY" \
        docker compose up -d --build scraper-api client-api ai ollama redis lelani-cache-api
    wait_for http://localhost:8001/health tender-client-api
    wait_for http://localhost:8000/health tender-scraper-api
}

deploy_login_api() {
    require JWT_SECRET
    cd "$ROOT/jwt"
    local hours="${SESSION_TIMEOUT_HOURS:-2}"
    if ! awk -v value="$hours" 'BEGIN { if (value ~ /^([0-9]+([.][0-9]*)?|[.][0-9]+)$/ && value + 0 > 0) exit 0; exit 1 }'; then
        echo "::error::SESSION_TIMEOUT_HOURS must be a positive, finite number of hours."
        exit 1
    fi
    if [ -z "${SMTP_HOST:-}" ] || [ -z "${SMTP_USERNAME:-}" ] || [ -z "${SMTP_PASSWORD:-}" ] || [ -z "${EMAIL_FROM:-}" ]; then
        echo "::warning::SMTP secrets are incomplete; password reset codes cannot be e-mailed."
    fi
    write_env . \
        "JWT_SECRET=$JWT_SECRET" \
        "INTERNAL_API_KEY=${INTERNAL_API_KEY:-}" \
        "EMAIL_FROM=${EMAIL_FROM:-}" \
        "SMTP_HOST=${SMTP_HOST:-}" \
        "SMTP_PORT=${SMTP_PORT:-587}" \
        "SMTP_USERNAME=${SMTP_USERNAME:-}" \
        "SMTP_PASSWORD=${SMTP_PASSWORD:-}" \
        "SMTP_USE_TLS=${SMTP_USE_TLS:-true}" \
        "SESSION_TIMEOUT_HOURS=$hours"
    # As the Login API's own workflow does: remove the old container first, so its fixed
    # name never clashes with the container of another Compose project.
    docker rm -f jwt-api || true
    docker compose -p "$PROJECT_LOGIN_API" up -d --build
    wait_for http://localhost:8006/health jwt-api
}

deploy_signup_api() {
    require JWT_SECRET EMAIL_CONFIRMATION_URL EMAIL_FROM SMTP_HOST SMTP_USERNAME SMTP_PASSWORD INTERNAL_API_KEY
    cd "$ROOT/Signup-api"
    [ -n "${ACCOUNT_DELETION_KEY:-}" ] || echo "::warning::ACCOUNT_DELETION_KEY is not set, so account deletion will answer 503."
    write_env . \
        "DATABASE_PATH=/data/tenders.db" \
        "JWT_SECRET=$JWT_SECRET" \
        "EMAIL_CONFIRMATION_URL=$EMAIL_CONFIRMATION_URL" \
        "LOGIN_URL=${LOGIN_URL:-}" \
        "EMAIL_FROM=$EMAIL_FROM" \
        "SMTP_HOST=$SMTP_HOST" \
        "SMTP_PORT=${SMTP_PORT:-587}" \
        "SMTP_USERNAME=$SMTP_USERNAME" \
        "SMTP_PASSWORD=$SMTP_PASSWORD" \
        "SMTP_USE_TLS=${SMTP_USE_TLS:-true}" \
        "VERIFICATION_TOKEN_EXPIRE_MINUTES=${VERIFICATION_TOKEN_EXPIRE_MINUTES:-30}" \
        "INTERNAL_API_KEY=$INTERNAL_API_KEY" \
        "ACCOUNT_DELETION_KEY=${ACCOUNT_DELETION_KEY:-}" \
        "AGENT_API_URL=${AGENT_API_URL:-http://tender-agent-api:9000}"
    docker compose -p "$PROJECT_SIGNUP_API" up -d --build
    wait_for http://localhost:8007/health tender-signup-api
}

deploy_notifications_api() {
    require JWT_SECRET INTERNAL_API_KEY
    cd "$ROOT/tender_apis"
    write_env . \
        "JWT_SECRET=$JWT_SECRET" \
        "JWT_ALGORITHM=${JWT_ALGORITHM:-HS256}" \
        "INTERNAL_API_KEY=$INTERNAL_API_KEY" \
        "APP_URL=${APP_URL:-}" \
        "PUBLIC_API_URL=${NOTIFICATIONS_PUBLIC_URL:-}" \
        "EMAIL_FROM=${EMAIL_FROM:-}" \
        "SMTP_HOST=${SMTP_HOST:-}" \
        "SMTP_PORT=${SMTP_PORT:-587}" \
        "SMTP_USERNAME=${SMTP_USERNAME:-}" \
        "SMTP_PASSWORD=${SMTP_PASSWORD:-}" \
        "SMTP_USE_TLS=${SMTP_USE_TLS:-true}"
    docker compose -p "$PROJECT_NOTIFICATIONS_API" up -d --build --force-recreate
    wait_for http://127.0.0.1:9007/health tender-notifications-api
}

deploy_alerts_api() {
    require JWT_SECRET
    cd "$ROOT/alerts-api"
    write_env . \
        "JWT_SECRET=$JWT_SECRET" \
        "DATABASE_PATH=/data/tenders.db" \
        "ALERT_SCAN_INTERVAL_SECONDS=300"
    docker compose -p "$PROJECT_ALERTS_API" up -d --build --force-recreate
    wait_for http://localhost:9005/health alerts-api
}

deploy_tender_ml() {
    cd "$ROOT/tender-ml"
    docker compose -p "$PROJECT_TENDER_ML" build
    # Exit code 2 means the saved model scored better and was kept, which is fine.
    docker compose -p "$PROJECT_TENDER_ML" run --rm tender-ml python train.py || [ $? -eq 2 ]
    docker compose -p "$PROJECT_TENDER_ML" up -d --force-recreate
    wait_for http://localhost:9004/health tender-ml
}

deploy_tender_ai_agent() {
    require AZURE_AI_API_KEY AZURE_AI_ENDPOINT AZURE_AI_DEPLOYMENT AI_SERVICE_API_KEY
    cd "$ROOT/tender-ai-agent"
    local image
    image="$(docker compose config --images agent-api)"
    # compose.yaml runs a pre-built image, so build it under that exact name first.
    docker build --pull -t "$image" .
    AI_SERVICE_URL=http://ai:8002 \
        docker compose up -d --force-recreate agent-api
    wait_for http://localhost:9000/ tender-agent-api
}

deploy_tender_ai_frontend() {
    require AGENT_URL LOGIN_URL
    cd "$ROOT/tender-ai-frontend"
    local image build_dir
    image="$(docker compose config --images frontend)"
    # Same build-time injection as the service's own workflow, done on a copy so the
    # checkout keeps its placeholders.
    build_dir="$(mktemp -d)"
    cp -R . "$build_dir"
    sed -i "s|__AGENT_URL__|${AGENT_URL}|g; s|__LOGIN_URL__|${LOGIN_URL}|g" "$build_dir/scripts/app.js"
    docker build -t "$image" "$build_dir"
    rm -rf "$build_dir"
    docker compose up -d --force-recreate frontend
    wait_for http://localhost:9001/ tender-ai-frontend
}

deploy_frontend() {
    require USER_SERVER_PORT
    cd "$ROOT/frontend"
    docker compose config --quiet
    docker compose build --no-cache
    docker compose up -d --force-recreate
    wait_for "http://localhost:${USER_SERVER_PORT}/login.html" tender-frontend
}

if [ $# -eq 0 ]; then
    echo "::error::No services given. Set the PRODUCTION_SERVICES variable, for example: frontend tender-ai-frontend"
    exit 1
fi

for service in "$@"; do
    echo "::group::Deploy $service"
    case "$service" in
        tender-scrapping-database) (deploy_tender_scrapping_database) ;;
        signup-api | Signup-api)   (deploy_signup_api) ;;
        notifications-api | tender_apis) (deploy_notifications_api) ;;
        alerts-api)                (deploy_alerts_api) ;;
        tender-ml)                 (deploy_tender_ml) ;;
        tender-ai-agent)           (deploy_tender_ai_agent) ;;
        tender-ai-frontend)        (deploy_tender_ai_frontend) ;;
        frontend)                  (deploy_frontend) ;;
        jwt | login-api)           (deploy_login_api) ;;
        cache-api)
            echo "::error::Refusing to deploy cache-api/: production runs ghcr.io/yglelani/lelani-cache-api from another repository (DEPLOYMENT.md)."
            exit 1
            ;;
        *)
            echo "::error::Unknown service: $service"
            exit 1
            ;;
    esac
    echo "::endgroup::"
done
echo "Production deployment finished: $*"
