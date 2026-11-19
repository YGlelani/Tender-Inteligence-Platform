#!/usr/bin/env bash
# Smoke test for a RUNNING staging stack (compose.staging.yaml). Read-only: it only
# sends GET requests to the staging ports on this machine.
#
#   bash scripts/staging/smoke_test.sh [.env.staging]
#
# Required checks fail the script; checks that need optional settings (Azure AI keys,
# a trained ML model) only print a warning.
set -uo pipefail

env_file="${1:-.env.staging}"
host="${SMOKE_TEST_HOST:-127.0.0.1}"
attempts="${SMOKE_TEST_ATTEMPTS:-24}"

setting() { # name default -> value from the env file, else the default
    local value=""
    if [ -f "$env_file" ]; then
        value="$(grep -E "^$1=" "$env_file" | tail -n 1 | cut -d= -f2- | tr -d '\r"'"'")"
    fi
    printf '%s' "${value:-$2}"
}

failures=0
pass() { echo "PASS $*"; }
warn() { echo "WARN $*"; [ -n "${GITHUB_ACTIONS:-}" ] && echo "::warning::$*"; return 0; }
fail() { echo "FAIL $*"; [ -n "${GITHUB_ACTIONS:-}" ] && echo "::error::$*"; failures=$((failures + 1)); }

# get <url>: body on stdout, retries until the server answers 2xx.
get() {
    local _
    for _ in $(seq 1 "$attempts"); do
        if curl -fsS --connect-timeout 3 --max-time 15 "$1" 2>/dev/null; then
            return 0
        fi
        sleep 5
    done
    return 1
}

check() { # name url [text that must appear in the body]
    local body
    if ! body="$(get "$2")"; then
        fail "$1: no successful answer from $2"
        return
    fi
    if [ -n "${3:-}" ] && ! printf '%s' "$body" | grep -Fq "$3"; then
        fail "$1: $2 answered without '$3': $(printf '%s' "$body" | head -c 300)"
        return
    fi
    pass "$1 ($2)"
}

check_optional() { # name url text-meaning-healthy
    local body
    if ! body="$(attempts=3 get "$2")"; then
        warn "$1: no successful answer from $2"
    elif ! printf '%s' "$body" | grep -Fq "$3"; then
        warn "$1: $2 is up but reports: $(printf '%s' "$body" | head -c 300)"
    else
        pass "$1 ($2)"
    fi
}

base="http://$host"
check "Client API"        "$base:$(setting STAGING_CLIENT_PORT 18001)/health"
check "Scraper API"       "$base:$(setting STAGING_SCRAPER_PORT 18000)/health" '"ok"'
check "Cache API (Redis + client API)" "$base:$(setting STAGING_CACHE_PORT 18003)/health" '"status":"ok"'
check "Login API"         "$base:$(setting STAGING_LOGIN_PORT 18006)/health"
check "Signup API"        "$base:$(setting STAGING_SIGNUP_PORT 18007)/health"
check "Notifications API" "$base:$(setting STAGING_NOTIFICATIONS_PORT 19007)/health" '"database":"connected"'
check "Alerts API"        "$base:$(setting STAGING_ALERTS_PORT 19005)/health"
check "AI agent"          "$base:$(setting STAGING_AGENT_PORT 19000)/"
check "Main site"         "$base:$(setting STAGING_FRONTEND_PORT 18009)/login.html" 'id="loginForm"'
# Proves the site was started with staging addresses, not production's.
check "Main site staging config" "$base:$(setting STAGING_FRONTEND_PORT 18009)/scripts/runtime-config.js" '"PORTS"'
check "AI workspace"      "$base:$(setting STAGING_AI_FRONTEND_PORT 19001)/"
check "AI workspace staging config" "$base:$(setting STAGING_AI_FRONTEND_PORT 19001)/scripts/runtime-config.js" '"AGENT_URL"'

check_optional "AI agent dependencies (Azure AI, embeddings, Redis)" "$base:$(setting STAGING_AGENT_PORT 19000)/health" '"status":"ok"'
check_optional "Tender ML model (needs: run --rm tender-ml python train.py)" "$base:$(setting STAGING_ML_PORT 19004)/health" '"status":"ok"'

if [ "$failures" -gt 0 ]; then
    echo "$failures staging check(s) failed."
    exit 1
fi
echo "All required staging checks passed."
