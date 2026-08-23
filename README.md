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

## Run without Docker

```bash
python server.py --host 127.0.0.1 --port 5225 --database data/long-time.db
```

Requires Python 3.11+ and no third-party dependencies.
