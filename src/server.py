from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from domain import (  # pyright: ignore[reportMissingImports]
    ValidationError,
    unit_catalog,
    validate_entry,
    validate_import,
    validate_task_item_checked,
    validate_tracker,
)
from storage import Storage  # pyright: ignore[reportMissingImports]

MAX_BODY = 65_536
MAX_IMPORT_BODY = 8_388_608


class ApiError(Exception):
    def __init__(self, status, code, message, field_errors=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field_errors = field_errors


def json_content_type(value):
    return (value or "").split(";", 1)[0].strip().lower() == "application/json"


def error_payload(code, message, field_errors=None):
    error = {"code": code, "message": message}
    if field_errors:
        error["field_errors"] = field_errors
    return {"error": error}


def send_json(status, payload):
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


class WebStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except (ValueError, OSError) as error:
            raise StarletteHTTPException(404) from error
        response.headers["Cache-Control"] = "no-cache"
        return response


async def read_json(request: Request) -> dict:
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ApiError(400, "invalid_json", "The request body must be valid JSON.") from error
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_json", "The request body must be a JSON object.")
    return payload


def record_or_404(record):
    if record is None:
        raise ApiError(404, "not_found", "That resource does not exist.")
    return send_json(200, record)


def create_app(db_path: Path, static_dir: Path) -> FastAPI:
    storage = Storage(db_path)
    storage.initialize()
    static_root = Path(static_dir).resolve()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ApiError)
    async def api_error_handler(_request, error: ApiError):
        return send_json(error.status, error_payload(error.code, error.message, error.field_errors))

    @app.exception_handler(ValidationError)
    async def validation_handler(_request, error: ValidationError):
        return send_json(400, error_payload("validation_error", "Check the highlighted fields.", error.fields))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, error: StarletteHTTPException):
        if request.url.path.startswith("/api/") or error.status_code == 405:
            code = "method_not_allowed" if error.status_code == 405 else "not_found"
            message = (
                "That method is not supported."
                if error.status_code == 405
                else "That resource does not exist."
            )
            return send_json(error.status_code, error_payload(code, message))
        return Response(status_code=error.status_code)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, _error):
        logging.exception("API request failed")
        if request.url.path.startswith("/api/"):
            return send_json(500, error_payload("server_error", "The server could not complete that request."))
        return Response(status_code=500)

    @app.middleware("http")
    async def harden_api(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "DELETE"}:
            if not json_content_type(request.headers.get("content-type")):
                return send_json(
                    415,
                    error_payload("unsupported_media_type", "Use Content-Type: application/json."),
                )
            limit = MAX_IMPORT_BODY if request.url.path == "/api/import" else MAX_BODY
            if len(await request.body()) > limit:
                return send_json(413, error_payload("request_too_large", "The request body is too large."))
        try:
            return await call_next(request)
        except (ValueError, OSError):
            if request.url.path.startswith("/api/"):
                return send_json(404, error_payload("not_found", "That resource does not exist."))
            raise StarletteHTTPException(404)

    @app.get("/api/trackers")
    def list_trackers():
        return send_json(200, storage.list_trackers())

    @app.get("/api/meta")
    def meta():
        return send_json(200, unit_catalog())

    @app.get("/api/export")
    def export():
        data = storage.export()
        body = json.dumps(data, separators=(",", ":")).encode("utf-8")
        filename = f"long-time-{data['exported_at'][:10]}.json"
        return Response(
            content=body,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/trackers")
    async def create_tracker(request: Request):
        return send_json(201, storage.create_tracker(validate_tracker(await read_json(request))))

    @app.put("/api/trackers/{tracker_id}")
    async def update_tracker(tracker_id: int, request: Request):
        return record_or_404(storage.update_tracker(tracker_id, validate_tracker(await read_json(request))))

    @app.delete("/api/trackers/{tracker_id}")
    def delete_tracker(tracker_id: int):
        if not storage.delete_tracker(tracker_id):
            raise ApiError(404, "not_found", "That resource does not exist.")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.post("/api/trackers/{tracker_id}/entries")
    async def create_entry(tracker_id: int, request: Request):
        record = storage.create_entry(tracker_id, validate_entry(await read_json(request)))
        if record is None:
            raise ApiError(404, "not_found", "That tracker does not exist.")
        return send_json(201, record)

    @app.put("/api/entries/{entry_id}")
    async def update_entry(entry_id: int, request: Request):
        return record_or_404(
            storage.update_entry(entry_id, validate_entry(await read_json(request), updating=True))
        )

    @app.delete("/api/entries/{entry_id}")
    def delete_entry(entry_id: int):
        if not storage.delete_entry(entry_id):
            raise ApiError(404, "not_found", "That resource does not exist.")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.post("/api/entries/{entry_id}/checkins")
    def create_checkin(entry_id: int):
        checkin = storage.create_checkin(entry_id)
        if checkin is None:
            raise ApiError(404, "not_found", "That resource does not exist.")
        return send_json(201, checkin)

    @app.put("/api/entries/{entry_id}/task-items/{item_id}")
    async def toggle_task_item(entry_id: int, item_id: int, request: Request):
        return record_or_404(
            storage.update_task_item_checked(
                entry_id, item_id, validate_task_item_checked(await read_json(request))
            )
        )

    @app.post("/api/import")
    async def import_data(request: Request):
        mode, trackers = validate_import(await read_json(request))
        return send_json(200, storage.import_data(trackers, mode))

    @app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    def api_unknown(full_path: str):
        raise ApiError(404, "not_found", "That resource does not exist.")

    app.mount("/", WebStaticFiles(directory=str(static_root), html=True), name="web")
    return app


def main():
    parser = argparse.ArgumentParser(description="Serve Long Time")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5225)
    parser.add_argument("--database", type=Path, default=Path("data/long-time.db"))
    parser.add_argument("--web-root", type=Path, default=Path(__file__).resolve().parent.parent / "web")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    app = create_app(args.database, args.web_root)
    logging.info("Long Time listening on http://%s:%s", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, timeout_keep_alive=30)


if __name__ == "__main__":
    main()
