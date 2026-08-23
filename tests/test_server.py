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
