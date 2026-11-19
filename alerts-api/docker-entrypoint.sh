#!/bin/sh
# Runs the service as the unprivileged "app" user (uid 10001).
# The container starts as root only so this script can let that user write the
# data volume (/data is shared with other services, and older files there are
# owned by root); then it drops root for good.
set -e
if [ "$(id -u)" = "0" ]; then
    for dir in ${WRITABLE_DIRS:-/data}; do
        if [ -d "$dir" ]; then
            chgrp -R 10001 "$dir"
            chmod -R g+rwX "$dir"
            find "$dir" -type d -exec chmod g+s {} +
        fi
    done
    export HOME=/home/app
    exec setpriv --reuid=10001 --regid=10001 --clear-groups -- "$@"
fi
exec "$@"
