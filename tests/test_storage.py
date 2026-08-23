import tempfile
import unittest
from pathlib import Path

from storage import Storage


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp_dir.name) / "long-time.db")
        self.storage.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tracker_and_entries_round_trip(self):
        tracker = self.storage.create_tracker({
            "title": "Learning piano",
            "description": "Practice that compounds",
            "started_at": "2023-11-16T17:30:00Z",
        })
        entry = self.storage.create_entry(tracker["id"], {
            "kind": "note", "title": "Practice became daily",
            "body": "Twenty minutes each morning", "occurred_at": "2024-07-04T06:00:00Z",
            "target_mode": None, "target_at": None, "target_value": None, "target_unit": None,
        })
        loaded = self.storage.list_trackers()
        self.assertEqual(loaded[0]["entries"][0]["id"], entry["id"])
        self.assertTrue(self.storage.delete_tracker(tracker["id"]))
        self.assertEqual(self.storage.list_trackers(), [])
        self.assertIsNone(self.storage.get_entry(entry["id"]))

    def test_updates_and_missing_records(self):
        tracker = self.storage.create_tracker({"title": "A", "description": "", "started_at": "2024-01-01T00:00:00Z"})
        updated = self.storage.update_tracker(tracker["id"], {"title": "B", "description": "changed", "started_at": tracker["started_at"]})
        self.assertEqual(updated["title"], "B")
        self.assertIsNone(self.storage.update_tracker(999, {"title": "X", "description": "", "started_at": tracker["started_at"]}))
        self.assertFalse(self.storage.delete_entry(999))
