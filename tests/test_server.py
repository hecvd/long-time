import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server import create_app


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.static_dir = root / "static"
        self.static_dir.mkdir()
        (self.static_dir / "index.html").write_text("<h1>Long Time</h1>", encoding="utf-8")
        (self.static_dir / "sw.js").write_text("// service worker", encoding="utf-8")
        self.db_path = root / "long-time.db"
        self.client = TestClient(create_app(self.db_path, self.static_dir))

    def tearDown(self):
        self.temp_dir.cleanup()

    def request(self, path, method="GET", payload=None, raw_body=None, headers=None):
        body = raw_body if raw_body is not None else (
            None if payload is None else json.dumps(payload).encode("utf-8")
        )
        if headers is None:
            headers = {"Content-Type": "application/json"} if body or method in {"POST", "PUT", "DELETE"} else {}
        response = self.client.request(method, path, content=body, headers=headers)
        return response.status_code, response.headers, response.content

    @staticmethod
    def media_type(headers):
        return (headers.get("content-type") or "").split(";", 1)[0].strip()

    def test_serves_index_without_directory_listing(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(self.media_type(headers), "text/html")
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
        self.assertIn("javascript", self.media_type(headers))

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

    def test_mutations_require_json_content_type(self):
        self.request("/api/trackers", "POST", {
            "title": "Piano", "description": "", "started_at": "2024-01-01T00:00:00Z",
        })
        wipe = {"mode": "replace", "trackers": []}
        status, _, body = self.request("/api/import", "POST", wipe, headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertEqual(json.loads(body)["error"]["code"], "unsupported_media_type")
        self.assertEqual(len(json.loads(self.request("/api/trackers")[2])), 1)

        status, _, _ = self.request("/api/import", "POST", wipe, headers={"Accept": "*/*"})
        self.assertEqual(status, 415)
        self.assertEqual(len(json.loads(self.request("/api/trackers")[2])), 1)

        status, _, body = self.request("/api/trackers", "POST", {
            "title": "Kept", "description": "", "started_at": "2024-01-01T00:00:00Z",
        }, headers={"Content-Type": "application/json; charset=utf-8"})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["title"], "Kept")

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
        kept = json.loads(body)
        self.assertIsNotNone(kept["task"])
        self.assertEqual(len(kept["task"]["checkins"]), 1)
        self.assertEqual(kept["title"], "Morning")

    def test_encoded_nul_path_is_a_clean_404(self):
        status, _, _ = self.request("/%00")
        self.assertEqual(status, 404)

    def test_meta_lists_duration_units(self):
        status, _, body = self.request("/api/meta")
        self.assertEqual(status, 200)
        catalog = json.loads(body)
        self.assertEqual([unit["id"] for unit in catalog["duration_units"]][-1], "years")
        self.assertEqual([unit["id"] for unit in catalog["task_period_units"]], ["day", "week"])

    def test_toggle_task_item_over_http(self):
        status, _, body = self.request("/api/trackers", "POST", {
            "title": "Habits", "description": "", "started_at": "2024-01-01T00:00:00Z",
        })
        tracker = json.loads(body)
        status, _, body = self.request(f"/api/trackers/{tracker['id']}/entries", "POST", {
            "kind": "milestone", "title": "Morning", "body": "", "target_mode": "none",
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"label": "Push-ups", "checked": False}]},
        })
        entry = json.loads(body)
        item_id = entry["task"]["items"][0]["id"]
        status, _, body = self.request(
            f"/api/entries/{entry['id']}/task-items/{item_id}", "PUT", {"checked": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["task"]["items"][0]["checked"])
        self.assertEqual(json.loads(body)["title"], "Morning")
        status, _, _ = self.request(f"/api/entries/{entry['id']}/task-items/999", "PUT", {"checked": True})
        self.assertEqual(status, 404)
