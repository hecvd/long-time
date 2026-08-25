#!/bin/sh
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

run() {
    exec python /app/src/server.py --host "$HOST" --port "$PORT" --database "$DATABASE" "$@"
}

# When started as root, own the mounted data dir with the requested ids and
# drop to that unprivileged user. When started with --user (already non-root),
# run as-is and rely on the volume already being writable.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$(dirname "$DATABASE")"
    chown -R "$PUID:$PGID" "$(dirname "$DATABASE")"
    exec su-exec "$PUID:$PGID" "$0" "$@"
fi

run "$@"
