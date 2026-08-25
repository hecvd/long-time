import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import create_server


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.static_dir = root / "static"
        self.static_dir.mkdir()
        (self.static_dir / "index.html").write_text("<h1>Long Time</h1>", encoding="utf-8")
        (self.static_dir / "sw.js").write_text("// service worker", encoding="utf-8")
        self.db_path = root / "long-time.db"
        self.server = create_server("127.0.0.1", 0, self.db_path, self.static_dir)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(self, path, method="GET", payload=None, raw_body=None, headers=None):
        body = raw_body if raw_body is not None else (
            None if payload is None else json.dumps(payload).encode("utf-8")
        )
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers=headers or ({"Content-Type": "application/json"} if body else {}),
        )
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    def test_serves_index_without_directory_listing(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "text/html")
        self.assertIn(b"Long Time", body)

        status, _, _ = self.request("/missing.txt")
        self.assertEqual(status, 404)

    def test_tracker_and_entry_api_workflow(self):
        status, _, body = self.request("/api/trackers", "POST", {
            "title": "Learning piano", "description": "",
            "started_at": "2023-11-16T18:30:00+01:00",
        })
        self.assertEqual(status, 201)
        tracker = json.loads(body)
        status, _, body = self.request(f"/api/trackers/{tracker['id']}/entries", "POST", {
            "kind": "milestone", "title": "Three years", "body": "Keep going",
            "target_mode": "duration", "target_value": 3, "target_unit": "years",
        })
        self.assertEqual(status, 201)
        milestone = json.loads(body)
        status, headers, body = self.request("/api/trackers")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body)[0]["entries"][0]["id"], milestone["id"])

        status, _, _ = self.request(f"/api/entries/{milestone['id']}", "DELETE")
        self.assertEqual(status, 204)
        status, _, _ = self.request(f"/api/trackers/{tracker['id']}", "DELETE")
        self.assertEqual(status, 204)

    def test_static_revalidates_with_etag(self):
        status, headers, _ = self.request("/")
        self.assertEqual(status, 200)
        etag = headers["ETag"]
        self.assertTrue(etag)
        self.assertEqual(headers["Cache-Control"], "no-cache")
        status, _, _ = self.request("/", headers={"If-None-Match": etag})
        self.assertEqual(status, 304)

        status, headers, _ = self.request("/sw.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get_content_type())

    def test_export_and_import_over_http(self):
        self.request("/api/trackers", "POST", {
            "title": "Piano", "description": "", "started_at": "2024-01-01T00:00:00Z",
        })
        status, headers, body = self.request("/api/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        export = json.loads(body)
        self.assertEqual(export["version"], 1)
        self.assertEqual(len(export["trackers"]), 1)

        status, _, body = self.request("/api/import", "POST", {"mode": "append", "trackers": export["trackers"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["trackers"], 1)
        self.assertEqual(len(json.loads(self.request("/api/trackers")[2])), 2)

        status, _, _ = self.request("/api/import", "POST", {"mode": "replace", "trackers": export["trackers"]})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(self.request("/api/trackers")[2])), 1)

        status, _, body = self.request("/api/import", "POST", {"mode": "merge", "trackers": []})
        self.assertEqual(status, 400)
        self.assertIn("field_errors", json.loads(body)["error"])

    def test_api_validation_missing_and_bad_json(self):
        status, _, body = self.request("/api/trackers", "POST", {"title": "", "started_at": "bad"})
        self.assertEqual(status, 400)
        self.assertIn("field_errors", json.loads(body)["error"])
        status, _, _ = self.request("/api/trackers/999", "DELETE")
        self.assertEqual(status, 404)
        status, _, body = self.request("/api/trackers", "POST", raw_body=b"{", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_json")

    def test_api_rejects_large_body_and_unsupported_method(self):
        status, _, _ = self.request("/api/trackers", "POST", raw_body=b"x" * 65_537, headers={"Content-Type": "application/json"})
        self.assertEqual(status, 413)
        status, _, _ = self.request("/api/trackers", "PATCH", {})
        self.assertEqual(status, 405)

    def test_task_milestone_checkin_workflow(self):
        status, _, body = self.request("/api/trackers", "POST", {
            "title": "Habits", "description": "", "started_at": "2024-01-01T00:00:00Z"})
        tracker = json.loads(body)
        status, _, body = self.request(f"/api/trackers/{tracker['id']}/entries", "POST", {
            "kind": "milestone", "title": "Morning", "body": "", "target_mode": "none",
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"label": "Push-ups", "checked": True}, {"label": "Read", "checked": False}]}})
        self.assertEqual(status, 201)
        entry = json.loads(body)

        status, _, body = self.request(f"/api/entries/{entry['id']}/checkins", "POST")
        self.assertEqual(status, 201)
        checkin = json.loads(body)
        self.assertTrue(checkin["changed"])
        self.assertEqual(checkin["checked_count"], 1)
        self.assertEqual(checkin["total_count"], 2)

        status, _, body = self.request("/api/trackers")
        loaded = json.loads(body)[0]["entries"][0]
        self.assertEqual(loaded["task"]["per_period"], 1)
        self.assertEqual(len(loaded["task"]["checkins"]), 1)

        status, _, body = self.request("/api/entries/999/checkins", "POST")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["message"], "That resource does not exist.")

        status, _, body = self.request(f"/api/entries/{entry['id']}", "PUT", {
            "kind": "milestone", "title": "Morning", "body": "",
            "target_mode": "duration", "target_value": 1, "target_unit": "years"})
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["task"])
