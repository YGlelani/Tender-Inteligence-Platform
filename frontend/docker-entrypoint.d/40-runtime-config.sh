#!/bin/sh
# Run by the nginx image's entrypoint at every container start (/docker-entrypoint.d).
# Writes scripts/runtime-config.js, which the pages load before their other scripts and
# which scripts/config.js, script.js and navigation.js read as window.APP_CONFIG.
#
# Optional settings (production sets neither, so the pages keep using the visitor's
# host name and the production ports):
#   USER_SERVER_IP          IP address or host name of the server running the APIs
#   FRONTEND_SERVICE_PORTS  comma-separated name=port pairs, for example
#                           "client=18001,login=18006" (names as in scripts/config.js)
# An invalid value stops the container with a message, rather than serving pages that
# call the wrong server.
set -eu

target=/usr/share/nginx/html/scripts/runtime-config.js
ip="${USER_SERVER_IP:-}"
ports="$(printf '%s' "${FRONTEND_SERVICE_PORTS:-}" | tr -d ' \t\r\n')"

case "$ip" in
    *[!A-Za-z0-9.-]*)
        echo "40-runtime-config: USER_SERVER_IP may only contain letters, digits, '.' and '-' (got '$ip')" >&2
        exit 1
        ;;
esac

json_ports=""
if [ -n "$ports" ]; then
    old_ifs=$IFS
    IFS=,
    for pair in $ports; do
        [ -n "$pair" ] || continue
        name=${pair%%=*}
        port=${pair#*=}
        case "$name" in
            "" | *[!A-Za-z]*)
                echo "40-runtime-config: bad service name in FRONTEND_SERVICE_PORTS: '$pair'" >&2
                exit 1
                ;;
        esac
        case "$port" in
            "" | *[!0-9]*)
                echo "40-runtime-config: bad port in FRONTEND_SERVICE_PORTS: '$pair'" >&2
                exit 1
                ;;
        esac
        if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
            echo "40-runtime-config: port out of range in FRONTEND_SERVICE_PORTS: '$pair'" >&2
            exit 1
        fi
        json_ports="${json_ports:+$json_ports,}\"$name\":$port"
    done
    IFS=$old_ifs
fi

settings=""
if [ -n "$ip" ]; then
    settings="\"USER_SERVER_IP\":\"$ip\""
fi
if [ -n "$json_ports" ]; then
    settings="${settings:+$settings,}\"PORTS\":{$json_ports}"
fi

{
    echo "// Generated at container start-up by docker-entrypoint.d/40-runtime-config.sh. Do not edit."
    echo "window.APP_CONFIG = Object.assign(window.APP_CONFIG || {}, {$settings});"
} > "$target"
chmod 644 "$target"

if [ -n "$settings" ]; then
    echo "40-runtime-config: wrote $target with {$settings}"
else
    echo "40-runtime-config: wrote $target (production defaults)"
fi
