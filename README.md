# long-time

Self hosted minimal tool to keep track of streaks for the long term.

## Run with Docker

The image is published to the GitHub Container Registry and stores its SQLite
database in a `/config` volume you mount from the host.

```bash
docker run -d \
  --name long-time \
  -p 5225:5225 \
  -e PUID=1000 \
  -e PGID=1000 \
  -v "$PWD/config:/config" \
  ghcr.io/hecvd/long-time:latest
```

Then open http://localhost:5225.

### docker compose

```yaml
services:
  long-time:
    image: ghcr.io/hecvd/long-time:latest
    container_name: long-time
    environment:
      - PUID=1000
      - PGID=1000
    ports:
      - "5225:5225"
    volumes:
      - ./config:/config
    restart: unless-stopped
```

```bash
docker compose up -d
```

### Configuration

| Variable   | Default                  | Description                                    |
| ---------- | ------------------------ | ---------------------------------------------- |
| `PUID`     | `1000`                   | User id that owns `/config` and runs the app.  |
| `PGID`     | `1000`                   | Group id that owns `/config` and runs the app. |
| `HOST`     | `0.0.0.0`                | Bind address inside the container.             |
| `PORT`     | `5225`                   | Port inside the container.                     |
| `DATABASE` | `/config/long-time.db`   | SQLite database path (keep it under `/config`). |

**Permissions:** the container starts as root only to `chown` the `/config`
volume to `PUID:PGID`, then drops to that unprivileged user. Set `PUID`/`PGID`
to match the owner of your host `config` directory (`id -u` / `id -g`).

To run fully rootless instead, pass `--user`; the volume must already be
writable by that user and `PUID`/`PGID` are ignored:

```bash
docker run --user "$(id -u):$(id -g)" -v "$PWD/config:/config" ... ghcr.io/hecvd/long-time:latest
```

## Offline use

The page keeps a copy of your ledger and its own assets, so you can open and
read it even while the server is down:

- The last successful `/api/trackers` response is cached in `localStorage` and
  shown instantly on load, then refreshed in the background (stale-while-
  revalidate). If the server is unreachable, the cached data stays on screen
  with a "Showing saved data" banner.
- A service worker (`web/sw.js`) precaches the app shell so the page itself
  loads offline.

Writing (create/edit/delete/import) still needs the server — only reading works
offline.

**Service workers require a secure context** — `localhost` or HTTPS. Over plain
`http://<lan-ip>` the browser blocks the service worker (the app falls back to
the data cache only). To get full offline on other devices, serve it over HTTPS
(next section).

### HTTPS on a local network

Keep this container plain HTTP and put a reverse proxy in front for TLS. Because
you own a domain, the proxy can obtain a real, publicly-trusted certificate via
the **DNS-01 ACME challenge** — which validates through a DNS record, so the
service never needs to be exposed to the internet. Point `long-time.<domain>`
at the LAN IP (public A record → private IP, or internal DNS) and you get
warning-free HTTPS locally.

Example `Caddyfile` (Caddy resolves the cert over DNS-01 with your provider's
API token; swap in your DNS plugin):

```
long-time.example.com {
    tls {
        dns cloudflare {env.CF_API_TOKEN}
    }
    reverse_proxy long-time:5225
}
```

Traefik (labels) and nginx-proxy-manager work the same way — set the DNS
provider credentials and route the host to the `long-time` service on port
`5225`. No app change required.

A ready-to-edit Traefik stack (Cloudflare DNS-01) lives in
[`docker-compose.traefik.yml`](docker-compose.traefik.yml): set the host and
email, provide `CF_DNS_API_TOKEN`, and add a DNS-only A record
`long-time.<domain>` → your LAN IP.

**Providing the token securely (Portainer):** the Portainer stack
*Environment variables* field is convenient but stored in Portainer's database
in clear text. To keep the token off disk-in-the-clear and out of the stack
definition, use a Docker secret file instead — lego reads any credential from a
`*_FILE` variable:

```yaml
    environment:
      - CF_DNS_API_TOKEN_FILE=/run/secrets/cf_dns_api_token
    secrets:
      - cf_dns_api_token

secrets:
  cf_dns_api_token:
    file: ./secrets/cf_dns_api_token.txt   # chmod 600, git-ignored, host-only
```

Create `./secrets/cf_dns_api_token.txt` on the host with the token, `chmod 600`,
and never commit it. Nothing sensitive then lives in the compose or Portainer's
database. A pre-wired stack is in
[`docker-compose.traefik.secrets.yml`](docker-compose.traefik.secrets.yml)
(`secrets/`, `letsencrypt/`, and `.env` are git-ignored).

## Run without Docker

Requires Python 3.11+ with FastAPI and uvicorn. [uv](https://docs.astral.sh/uv/) is the supported way to install dependencies and run commands.

```bash
uv sync
uv run python src/server.py --host 127.0.0.1 --port 5225 --database data/long-time.db
```

Or, with any 3.11+ interpreter after installing the project dependencies:

```bash
python src/server.py --host 127.0.0.1 --port 5225 --database data/long-time.db
```

## Layout

```
src/     backend: HTTP server, SQLite storage, domain logic, migrations
web/     frontend: static HTML, CSS, JS served at the web root
tests/   Python and Node tests
```

## Tests and lint

```bash
uv run pytest                    # Python API, storage, and domain tests
uv run ruff check src tests      # Python lint
uv run ruff format src tests     # Python format (opt-in; not required in CI)
npm ci                           # JS toolchain (Biome)
npm run lint                     # JS lint and format check
npm run format                   # JS lint/format write
npm test                         # frontend logic tests
```
