FROM python:3.13-alpine

# su-exec drops privileges to the requested PUID/PGID at runtime.
RUN apk add --no-cache su-exec
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN chmod +x /app/docker-entrypoint.sh

ENV PUID=1000 \
    PGID=1000 \
    HOST=0.0.0.0 \
    PORT=5225 \
    DATABASE=/config/long-time.db \
    PATH="/app/.venv/bin:$PATH"

VOLUME /config
EXPOSE 5225

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD wget -qO- "http://127.0.0.1:${PORT}/api/trackers" >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
