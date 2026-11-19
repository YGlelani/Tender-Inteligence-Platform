#!/bin/sh
# Run by the nginx image's entrypoint at every container start (/docker-entrypoint.d).
# Writes scripts/runtime-config.js (window.APP_CONFIG), which index.html loads first.
#
# Optional settings. Production sets none of them: its addresses are written into
# scripts/app.js at build time (__AGENT_URL__ / __LOGIN_URL__), and this script then
# only writes an empty configuration and leaves nginx.conf untouched.
#   AGENT_URL       address of the AI agent API, e.g. http://203.0.113.10:19000
#   LOGIN_URL       login page of the main site, e.g. http://203.0.113.10:18009/login.html
#   MAIN_SITE_PORT  port of the main site on this host (default in the page: 8009)
# When AGENT_URL is set, the Content-Security-Policy in nginx.conf is changed to allow
# that address instead of port 9000 of this host.
# An invalid value stops the container with a message.
set -eu

target=/usr/share/nginx/html/scripts/runtime-config.js
conf=/etc/nginx/conf.d/default.conf
agent_url="${AGENT_URL:-}"
login_url="${LOGIN_URL:-}"
main_port="${MAIN_SITE_PORT:-}"

check_url() { # name value
    case "$2" in
        "") return 0 ;;
        http://* | https://*) ;;
        *) echo "40-runtime-config: $1 must start with http:// or https:// (got '$2')" >&2; exit 1 ;;
    esac
    case "$2" in
        *[!A-Za-z0-9.:/_?=\&%#-]*)
            echo "40-runtime-config: $1 contains characters that are not allowed (got '$2')" >&2
            exit 1
            ;;
    esac
}
check_url AGENT_URL "$agent_url"
check_url LOGIN_URL "$login_url"
case "$main_port" in
    *[!0-9]*) echo "40-runtime-config: MAIN_SITE_PORT must be a number (got '$main_port')" >&2; exit 1 ;;
esac

settings=""
add() { settings="${settings:+$settings,}$1"; }
if [ -n "$agent_url" ]; then add "\"AGENT_URL\":\"${agent_url%/}\""; fi
if [ -n "$login_url" ]; then add "\"LOGIN_URL\":\"$login_url\""; fi
if [ -n "$main_port" ]; then add "\"MAIN_SITE_PORT\":$main_port"; fi

{
    echo "// Generated at container start-up by docker-entrypoint.d/40-runtime-config.sh. Do not edit."
    echo "window.APP_CONFIG = Object.assign(window.APP_CONFIG || {}, {$settings});"
} > "$target"
chmod 644 "$target"

if [ -n "$agent_url" ]; then
    origin="$(printf '%s' "$agent_url" | sed -E 's#^(https?://[^/]+).*#\1#')"
    case "$origin" in
        *[!A-Za-z0-9.:/-]*) echo "40-runtime-config: AGENT_URL host part is not valid (got '$origin')" >&2; exit 1 ;;
    esac
    sed -i 's|\$scheme://\$host:9000|'"$origin"'|g' "$conf"
    echo "40-runtime-config: Content-Security-Policy now allows $origin"
fi

if [ -n "$settings" ]; then
    echo "40-runtime-config: wrote $target with {$settings}"
else
    echo "40-runtime-config: wrote $target (production: build-time addresses apply)"
fi
