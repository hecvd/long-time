import sqlite3
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
        assert tracker is not None
        entry = self.storage.create_entry(tracker["id"], {
            "kind": "note", "title": "Practice became daily",
            "body": "Twenty minutes each morning", "occurred_at": "2024-07-04T06:00:00Z",
            "target_mode": None, "target_at": None, "target_value": None, "target_unit": None,
        })
        assert entry is not None
        loaded = self.storage.list_trackers()
        self.assertEqual(loaded[0]["entries"][0]["id"], entry["id"])
        self.assertTrue(self.storage.delete_tracker(tracker["id"]))
        self.assertEqual(self.storage.list_trackers(), [])
        self.assertIsNone(self.storage.get_entry(entry["id"]))

    def test_initialize_migrates_month_units_without_losing_entries(self):
        self.storage.path.unlink()
        legacy = sqlite3.connect(self.storage.path)
        try:
            legacy.executescript("""
                CREATE TABLE trackers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    description TEXT NOT NULL, started_at TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                    occurred_at TEXT, target_mode TEXT, target_at TEXT,
                    target_value REAL,
                    target_unit TEXT CHECK(target_unit IN ('hours', 'days', 'weeks', 'years') OR target_unit IS NULL),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                INSERT INTO trackers VALUES (1, 'Existing', '', '2024-01-31T10:15:00Z', 'now', 'now');
                INSERT INTO entries VALUES (1, 1, 'note', 'Kept', '', '2024-02-01T00:00:00Z', NULL, NULL, NULL, NULL, 'now', 'now');
            """)
            legacy.commit()
        finally:
            legacy.close()

        self.storage.initialize()
        created = self.storage.create_entry(1, {
            "kind": "milestone", "title": "Month", "body": "", "occurred_at": None,
            "target_mode": "duration", "target_at": None, "target_value": 1, "target_unit": "months",
        })

        assert created is not None
        self.assertEqual(created["target_unit"], "months")
        self.assertEqual([entry["title"] for entry in self.storage.list_trackers()[0]["entries"]], ["Kept", "Month"])

    def test_updates_and_missing_records(self):
        tracker = self.storage.create_tracker({"title": "A", "description": "", "started_at": "2024-01-01T00:00:00Z"})
        assert tracker is not None
        updated = self.storage.update_tracker(tracker["id"], {"title": "B", "description": "changed", "started_at": tracker["started_at"]})
        assert updated is not None
        self.assertEqual(updated["title"], "B")
        self.assertIsNone(self.storage.update_tracker(999, {"title": "X", "description": "", "started_at": tracker["started_at"]}))
        self.assertFalse(self.storage.delete_entry(999))
