import sqlite3
import tempfile
import unittest
from pathlib import Path

from domain import validate_import
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

    def test_export_and_import_round_trip(self):
        tracker = self.storage.create_tracker({"title": "Piano", "description": "d", "started_at": "2024-01-01T00:00:00Z"})
        assert tracker is not None
        self.storage.create_entry(tracker["id"], {
            "kind": "note", "title": "Started", "body": "", "occurred_at": "2024-02-01T00:00:00Z",
            "target_mode": None, "target_at": None, "target_value": None, "target_unit": None,
        })
        snapshot = self.storage.export()
        self.assertEqual(snapshot["version"], 1)
        payload = [
            {**tracker_data, "entries": tracker_data["entries"]}
            for tracker_data in snapshot["trackers"]
        ]

        appended = self.storage.import_data(payload, "append")
        self.assertEqual(appended, {"trackers": 1, "entries": 1})
        self.assertEqual(len(self.storage.list_trackers()), 2)

        replaced = self.storage.import_data(payload, "replace")
        self.assertEqual(replaced, {"trackers": 1, "entries": 1})
        trackers = self.storage.list_trackers()
        self.assertEqual(len(trackers), 1)
        self.assertEqual(trackers[0]["title"], "Piano")
        self.assertEqual(trackers[0]["entries"][0]["title"], "Started")

    def test_four_week_unit_is_accepted(self):
        tracker = self.storage.create_tracker({"title": "T", "description": "", "started_at": "2024-01-01T00:00:00Z"})
        assert tracker is not None
        entry = self.storage.create_entry(tracker["id"], {
            "kind": "milestone", "title": "Six weeks", "body": "", "occurred_at": None,
            "target_mode": "duration", "target_at": None, "target_value": 1.5, "target_unit": "four_weeks",
        })
        assert entry is not None
        self.assertEqual(entry["target_unit"], "four_weeks")
        self.assertEqual(entry["target_value"], 1.5)

    def test_updates_and_missing_records(self):
        tracker = self.storage.create_tracker({"title": "A", "description": "", "started_at": "2024-01-01T00:00:00Z"})
        assert tracker is not None
        updated = self.storage.update_tracker(tracker["id"], {"title": "B", "description": "changed", "started_at": tracker["started_at"]})
        assert updated is not None
        self.assertEqual(updated["title"], "B")
        self.assertIsNone(self.storage.update_tracker(999, {"title": "X", "description": "", "started_at": tracker["started_at"]}))
        self.assertFalse(self.storage.delete_entry(999))

    def _task_tracker(self):
        return self.storage.create_tracker({"title": "Habits", "description": "", "started_at": "2024-01-01T00:00:00Z"})

    def test_create_task_milestone_persists_config_and_items(self):
        tracker = self._task_tracker()
        entry = self.storage.create_entry(tracker["id"], {
            "kind": "milestone", "title": "Morning", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": None, "label": "Push-ups", "checked": True, "position": 0},
                               {"id": None, "label": "Read", "checked": False, "position": 1}]},
        })
        assert entry is not None
        loaded = self.storage.list_trackers()[0]["entries"][0]
        self.assertEqual(loaded["task"]["per_period"], 1)
        self.assertEqual([i["label"] for i in loaded["task"]["items"]], ["Push-ups", "Read"])
        self.assertEqual([i["checked"] for i in loaded["task"]["items"]], [True, False])
        self.assertEqual(loaded["task"]["checkins"], [])

    def test_non_task_entries_expose_task_none(self):
        tracker = self._task_tracker()
        self.storage.create_entry(tracker["id"], {
            "kind": "note", "title": "N", "body": "", "occurred_at": "2024-02-01T00:00:00Z",
            "target_mode": None, "target_at": None, "target_value": None, "target_unit": None, "task": None})
        self.assertIsNone(self.storage.list_trackers()[0]["entries"][0]["task"])

    def _make_task(self, items):
        tracker = self._task_tracker()
        entry = self.storage.create_entry(tracker["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": None, "label": label, "checked": checked, "position": pos}
                               for pos, (label, checked) in enumerate(items)]}})
        loaded = self.storage.list_trackers()[0]["entries"][0]["task"]["items"]
        return entry, {item["label"]: item["id"] for item in loaded}

    def test_first_checkin_is_always_changed(self):
        entry, _ = self._make_task([("A", True), ("B", False)])
        checkin = self.storage.create_checkin(entry["id"])
        self.assertTrue(checkin["changed"])
        self.assertEqual(checkin["checked_count"], 1)
        self.assertEqual(checkin["total_count"], 2)

    def test_unchanged_checkin_still_stores_ids(self):
        entry, ids = self._make_task([("A", True)])
        self.storage.create_checkin(entry["id"])
        second = self.storage.create_checkin(entry["id"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["checked_item_ids"], [ids["A"]])
        task = self.storage.list_trackers()[0]["entries"][0]["task"]
        self.assertEqual(len(task["checkins"]), 2)
        self.assertEqual(sum(1 for c in task["checkins"] if c["changed"]), 1)

    def test_toggling_an_item_marks_the_next_checkin_changed(self):
        entry, ids = self._make_task([("A", True), ("B", False)])
        self.storage.create_checkin(entry["id"])
        self.storage.update_entry(entry["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": ids["A"], "label": "A", "checked": True, "position": 0},
                               {"id": ids["B"], "label": "B", "checked": True, "position": 1}]}})
        second = self.storage.create_checkin(entry["id"])
        self.assertTrue(second["changed"])
        self.assertEqual(sorted(second["checked_item_ids"]), sorted([ids["A"], ids["B"]]))

    def test_renaming_an_item_does_not_mark_changed(self):
        entry, ids = self._make_task([("A", True)])
        self.storage.create_checkin(entry["id"])
        self.storage.update_entry(entry["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": ids["A"], "label": "A renamed", "checked": True, "position": 0}]}})
        second = self.storage.create_checkin(entry["id"])
        self.assertFalse(second["changed"])

    def test_adding_an_item_changes_total_and_marks_changed(self):
        entry, ids = self._make_task([("A", True)])
        self.storage.create_checkin(entry["id"])
        self.storage.update_entry(entry["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": ids["A"], "label": "A", "checked": True, "position": 0},
                               {"id": None, "label": "B", "checked": False, "position": 1}]}})
        second = self.storage.create_checkin(entry["id"])
        self.assertTrue(second["changed"])
        self.assertEqual(second["total_count"], 2)

    def test_checkin_on_missing_or_non_task_returns_none(self):
        self.assertIsNone(self.storage.create_checkin(999))
        tracker = self._task_tracker()
        plain = self.storage.create_entry(tracker["id"], {
            "kind": "milestone", "title": "Plain", "body": "", "occurred_at": None,
            "target_mode": "duration", "target_at": None, "target_value": 1, "target_unit": "years", "task": None})
        self.assertIsNone(self.storage.create_checkin(plain["id"]))

    def test_delete_entry_cascades_to_task_rows(self):
        entry, _ = self._make_task([("A", True)])
        self.storage.create_checkin(entry["id"])
        self.assertTrue(self.storage.delete_entry(entry["id"]))
        with self.storage._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_config").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_items").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_checkins").fetchone()[0], 0)

    def test_clearing_task_overlay_deletes_checkins(self):
        entry, _ = self._make_task([("A", True)])
        self.storage.create_checkin(entry["id"])
        cleared = self.storage.update_entry(entry["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "duration", "target_at": None, "target_value": 1, "target_unit": "years",
            "task": None,
        })
        assert cleared is not None
        self.assertIsNone(cleared["task"])
        with self.storage._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_config WHERE entry_id=?", (entry["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_items WHERE entry_id=?", (entry["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_checkins WHERE entry_id=?", (entry["id"],)).fetchone()[0], 0)
        restored = self.storage.update_entry(entry["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "duration", "target_at": None, "target_value": 1, "target_unit": "years",
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": None, "label": "A", "checked": False, "position": 0}]},
        })
        assert restored is not None
        self.assertEqual(restored["task"]["checkins"], [])

    def test_update_task_reconciles_items(self):
        tracker = self._task_tracker()
        entry = self.storage.create_entry(tracker["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": None, "label": "A", "checked": False, "position": 0},
                               {"id": None, "label": "B", "checked": False, "position": 1}]}})
        items = self.storage.list_trackers()[0]["entries"][0]["task"]["items"]
        keep_id = items[0]["id"]
        self.storage.update_entry(entry["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 2, "period_unit": "week",
                     "items": [{"id": keep_id, "label": "A renamed", "checked": True, "position": 0},
                               {"id": None, "label": "C", "checked": False, "position": 1}]}})
        task = self.storage.list_trackers()[0]["entries"][0]["task"]
        self.assertEqual(task["per_period"], 2)
        self.assertEqual(task["period_unit"], "week")
        active = [i for i in task["items"] if i["active"]]
        self.assertEqual([i["label"] for i in active], ["A renamed", "C"])
        removed = [i for i in task["items"] if not i["active"]]
        self.assertEqual([i["label"] for i in removed], ["B"])

    def test_validate_import_then_import_data_preserves_overlay(self):
        entry, ids = self._make_task([("A", False), ("B", False)])
        self.storage.create_checkin(entry["id"])
        self.storage.update_entry(entry["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": ids["A"], "label": "A", "checked": True, "position": 0},
                               {"id": ids["B"], "label": "B", "checked": False, "position": 1}]}})
        self.storage.create_checkin(entry["id"])
        self.storage.create_checkin(entry["id"])
        self.storage.update_entry(entry["id"], {
            "kind": "milestone", "title": "M", "body": "", "occurred_at": None,
            "target_mode": "none", "target_at": None, "target_value": None, "target_unit": None,
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"id": ids["A"], "label": "A", "checked": True, "position": 0}]}})

        snapshot = self.storage.export()
        mode, trackers = validate_import({"mode": "replace", "trackers": snapshot["trackers"]})
        self.storage.import_data(trackers, mode)

        task = self.storage.list_trackers()[0]["entries"][0]["task"]
        self.assertEqual(task["per_period"], 1)
        active_ids = {item["id"] for item in task["items"] if item["active"]}
        self.assertEqual([i["label"] for i in task["items"] if not i["active"]], ["B"])
        changed = [c for c in task["checkins"] if c["changed"]]
        unchanged = [c for c in task["checkins"] if not c["changed"]]
        self.assertEqual(changed[0]["checked_item_ids"], [])
        self.assertTrue(set(changed[-1]["checked_item_ids"]).issubset(active_ids))
        self.assertEqual(len(changed[-1]["checked_item_ids"]), 1)
        self.assertEqual(unchanged[0]["checked_item_ids"], changed[-1]["checked_item_ids"])
