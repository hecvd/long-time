from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _dict(row):
        return dict(row) if row is not None else None

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS trackers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                    description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 500),
                    started_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK(kind IN ('note', 'milestone')),
                    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                    body TEXT NOT NULL DEFAULT '' CHECK(length(body) <= 2000),
                    occurred_at TEXT,
                    target_mode TEXT CHECK(target_mode IN ('date', 'duration') OR target_mode IS NULL),
                    target_at TEXT,
                    target_value REAL,
                    target_unit TEXT CHECK(target_unit IN ('hours', 'days', 'weeks', 'months', 'years') OR target_unit IS NULL),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS entries_tracker_id_idx ON entries(tracker_id);
            """)
            entries_sql = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries'"
            ).fetchone()["sql"]
            if "'months'" not in entries_sql:
                db.executescript("""
                    ALTER TABLE entries RENAME TO entries_without_months;
                    CREATE TABLE entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
                        kind TEXT NOT NULL CHECK(kind IN ('note', 'milestone')),
                        title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                        body TEXT NOT NULL DEFAULT '' CHECK(length(body) <= 2000),
                        occurred_at TEXT,
                        target_mode TEXT CHECK(target_mode IN ('date', 'duration') OR target_mode IS NULL),
                        target_at TEXT,
                        target_value REAL,
                        target_unit TEXT CHECK(target_unit IN ('hours', 'days', 'weeks', 'months', 'years') OR target_unit IS NULL),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO entries
                    SELECT * FROM entries_without_months;
                    DROP TABLE entries_without_months;
                    CREATE INDEX entries_tracker_id_idx ON entries(tracker_id);
                """)

    def list_trackers(self):
        with self._connect() as db:
            trackers = [dict(row) for row in db.execute("SELECT * FROM trackers ORDER BY id")]
            entries = [dict(row) for row in db.execute("SELECT * FROM entries ORDER BY id")]
        grouped = {tracker["id"]: [] for tracker in trackers}
        for entry in entries:
            grouped.get(entry["tracker_id"], []).append(entry)
        for tracker in trackers:
            tracker["entries"] = grouped[tracker["id"]]
        return trackers

    def get_tracker(self, tracker_id):
        return next((item for item in self.list_trackers() if item["id"] == tracker_id), None)

    def create_tracker(self, data):
        now = self._now()
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO trackers(title, description, started_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (data["title"], data["description"], data["started_at"], now, now),
            )
            tracker_id = cursor.lastrowid
        return self.get_tracker(tracker_id)

    def update_tracker(self, tracker_id, data):
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE trackers SET title=?, description=?, started_at=?, updated_at=? WHERE id=?",
                (data["title"], data["description"], data["started_at"], self._now(), tracker_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_tracker(tracker_id)

    def delete_tracker(self, tracker_id):
        with self._connect() as db:
            return db.execute("DELETE FROM trackers WHERE id=?", (tracker_id,)).rowcount > 0

    def get_entry(self, entry_id):
        with self._connect() as db:
            return self._dict(db.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone())

    def create_entry(self, tracker_id, data):
        now = self._now()
        values = tuple(data[key] for key in ("kind", "title", "body", "occurred_at", "target_mode", "target_at", "target_value", "target_unit"))
        with self._connect() as db:
            if db.execute("SELECT 1 FROM trackers WHERE id=?", (tracker_id,)).fetchone() is None:
                return None
            cursor = db.execute(
                "INSERT INTO entries(tracker_id,kind,title,body,occurred_at,target_mode,target_at,target_value,target_unit,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (tracker_id, *values, now, now),
            )
            db.execute("UPDATE trackers SET updated_at=? WHERE id=?", (now, tracker_id))
            entry_id = cursor.lastrowid
        return self.get_entry(entry_id)

    def update_entry(self, entry_id, data):
        existing = self.get_entry(entry_id)
        if existing is None:
            return None
        now = self._now()
        values = tuple(data[key] for key in ("kind", "title", "body", "occurred_at", "target_mode", "target_at", "target_value", "target_unit"))
        with self._connect() as db:
            db.execute(
                "UPDATE entries SET kind=?,title=?,body=?,occurred_at=?,target_mode=?,target_at=?,target_value=?,target_unit=?,updated_at=? WHERE id=?",
                (*values, now, entry_id),
            )
            db.execute("UPDATE trackers SET updated_at=? WHERE id=?", (now, existing["tracker_id"]))
        return self.get_entry(entry_id)

    def delete_entry(self, entry_id):
        existing = self.get_entry(entry_id)
        if existing is None:
            return False
        with self._connect() as db:
            deleted = db.execute("DELETE FROM entries WHERE id=?", (entry_id,)).rowcount > 0
            if deleted:
                db.execute("UPDATE trackers SET updated_at=? WHERE id=?", (self._now(), existing["tracker_id"]))
            return deleted
