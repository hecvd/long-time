FROM python:3.13-alpine

# su-exec drops privileges to the requested PUID/PGID at runtime.
RUN apk add --no-cache su-exec

WORKDIR /app
COPY . .
RUN chmod +x /app/docker-entrypoint.sh

ENV PUID=1000 \
    PGID=1000 \
    HOST=0.0.0.0 \
    PORT=5225 \
    DATABASE=/config/long-time.db

VOLUME /config
EXPOSE 5225

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD wget -qO- "http://127.0.0.1:${PORT}/api/trackers" >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
