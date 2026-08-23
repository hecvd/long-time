from __future__ import annotations

import argparse
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


def create_handler(db_path: Path, static_dir: Path):
    static_root = static_dir.resolve()

    class LongTimeHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path.startswith("/api/") or path == "/api":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            relative = "index.html" if path == "/" else unquote(path).lstrip("/")
            candidate = (static_root / relative).resolve()
            if static_root not in candidate.parents and candidate != static_root:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return LongTimeHandler


def create_server(host: str, port: int, db_path: Path, static_dir: Path):
    return ThreadingHTTPServer((host, port), create_handler(db_path, static_dir))


def main():
    parser = argparse.ArgumentParser(description="Serve Long Time")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--database", type=Path, default=Path("data/long-time.db"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    server = create_server(args.host, args.port, args.database, root)
    print(f"Long Time: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
