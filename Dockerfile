FROM python:3.14-alpine

# su-exec drops privileges to the requested PUID/PGID at runtime.
RUN apk add --no-cache su-exec
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

WORKDIR /app

ENV PUID=1000 \
    PGID=1000 \
    HOST=0.0.0.0 \
    PORT=5225 \
    DATABASE=/config/long-time.db \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_SYSTEM_PYTHON=1

COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && python -c "import uvicorn"

COPY . .
RUN chmod +x /app/docker-entrypoint.sh

VOLUME /config
EXPOSE 5225

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD wget -qO- "http://127.0.0.1:${PORT}/api/trackers" >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
