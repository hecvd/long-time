from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from domain import ValidationError, validate_entry, validate_tracker  # pyright: ignore[reportMissingImports]
from storage import Storage  # pyright: ignore[reportMissingImports]

MAX_BODY = 65_536
TRACKER_PATH = re.compile(r"^/api/trackers/(\d+)$")
TRACKER_ENTRIES_PATH = re.compile(r"^/api/trackers/(\d+)/entries$")
ENTRY_PATH = re.compile(r"^/api/entries/(\d+)$")


class ApiError(Exception):
    def __init__(self, status, code, message, field_errors=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field_errors = field_errors


def create_handler(storage: Storage, static_dir: Path):
    static_root = static_dir.resolve()

    class LongTimeHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            logging.info("%s - %s", self.address_string(), format % args)

        def send_json(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_api_error(self, status, code, message, field_errors=None):
            error = {"code": code, "message": message}
            if field_errors:
                error["field_errors"] = field_errors
            self.send_json(status, {"error": error})

        def read_json(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ApiError(400, "invalid_request", "Invalid request body.") from error
            if length > MAX_BODY:
                raise ApiError(413, "request_too_large", "The request body is too large.")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ApiError(400, "invalid_json", "The request body must be valid JSON.") from error
            if not isinstance(payload, dict):
                raise ApiError(400, "invalid_json", "The request body must be a JSON object.")
            return payload

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/trackers":
                self.send_json(200, storage.list_trackers())
                return
            if path.startswith("/api"):
                self.send_api_error(404, "not_found", "That resource does not exist.")
                return
            self.serve_static(path)

        def do_POST(self):
            self.handle_mutation("POST")

        def do_PUT(self):
            self.handle_mutation("PUT")

        def do_DELETE(self):
            self.handle_mutation("DELETE")

        def do_PATCH(self):
            self.send_api_error(405, "method_not_allowed", "That method is not supported.")

        def handle_mutation(self, method):
            path = urlsplit(self.path).path
            try:
                if method == "POST" and path == "/api/trackers":
                    self.send_json(201, storage.create_tracker(validate_tracker(self.read_json())))
                    return
                tracker_match = TRACKER_PATH.fullmatch(path)
                if tracker_match and method in {"PUT", "DELETE"}:
                    tracker_id = int(tracker_match.group(1))
                    if method == "PUT":
                        record = storage.update_tracker(tracker_id, validate_tracker(self.read_json()))
                        self._record_or_404(record)
                    else:
                        self._delete_or_404(storage.delete_tracker(tracker_id))
                    return
                nested_match = TRACKER_ENTRIES_PATH.fullmatch(path)
                if nested_match and method == "POST":
                    record = storage.create_entry(int(nested_match.group(1)), validate_entry(self.read_json()))
                    if record is None:
                        raise ApiError(404, "not_found", "That tracker does not exist.")
                    self.send_json(201, record)
                    return
                entry_match = ENTRY_PATH.fullmatch(path)
                if entry_match and method in {"PUT", "DELETE"}:
                    entry_id = int(entry_match.group(1))
                    if method == "PUT":
                        self._record_or_404(storage.update_entry(entry_id, validate_entry(self.read_json())))
                    else:
                        self._delete_or_404(storage.delete_entry(entry_id))
                    return
                raise ApiError(405, "method_not_allowed", "That method is not supported.")
            except ValidationError as error:
                self.send_api_error(400, "validation_error", "Check the highlighted fields.", error.fields)
            except ApiError as error:
                self.send_api_error(error.status, error.code, error.message, error.field_errors)
            except Exception:
                logging.exception("API request failed")
                self.send_api_error(500, "server_error", "The server could not complete that request.")

        def _record_or_404(self, record):
            if record is None:
                raise ApiError(404, "not_found", "That resource does not exist.")
            self.send_json(200, record)

        def _delete_or_404(self, deleted):
            if not deleted:
                raise ApiError(404, "not_found", "That resource does not exist.")
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def serve_static(self, path):
            relative = "index.html" if path == "/" else unquote(path).lstrip("/")
            candidate = (static_root / relative).resolve()
            if (static_root not in candidate.parents and candidate != static_root) or not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return LongTimeHandler


def create_server(host: str, port: int, db_path: Path, static_dir: Path):
    storage = Storage(db_path)
    storage.initialize()
    return ThreadingHTTPServer((host, port), create_handler(storage, static_dir))


def main():
    parser = argparse.ArgumentParser(description="Serve Long Time")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5225)
    parser.add_argument("--database", type=Path, default=Path("data/long-time.db"))
    parser.add_argument("--web-root", type=Path, default=Path(__file__).resolve().parent.parent / "web")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.database, args.web_root)
    print(f"Long Time: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
