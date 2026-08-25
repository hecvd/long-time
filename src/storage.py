from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from domain import ValidationError, resolve_milestone_target

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
ENTRY_FIELDS = ("kind", "title", "body", "occurred_at", "target_mode", "target_at", "target_value", "target_unit")


def _sql_statements(sql: str):
    for chunk in sql.split(";"):
        statement = chunk.strip()
        if statement:
            yield statement


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _connect(self, immediate=False):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        if immediate:
            connection.isolation_level = "IMMEDIATE"
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
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _dict(row):
        return dict(row) if row is not None else None

    @staticmethod
    def _checked_item_ids(raw):
        # TEXT "[]" is a real empty snapshot; SQL NULL means "not stored".
        return json.loads(raw) if raw else None

    @staticmethod
    def _overlay(config, item_rows, checkin_rows):
        if not config:
            return None
        return {
            "per_period": config["per_period"],
            "period_unit": config["period_unit"],
            "items": [
                {
                    "id": item["id"], "label": item["label"], "position": item["position"],
                    "checked": bool(item["checked"]), "active": bool(item["active"]),
                }
                for item in item_rows
            ],
            "checkins": [
                {
                    "id": checkin["id"], "occurred_at": checkin["occurred_at"],
                    "checked_count": checkin["checked_count"], "total_count": checkin["total_count"],
                    "changed": bool(checkin["changed"]),
                    "checked_item_ids": Storage._checked_item_ids(checkin["checked_item_ids"]),
                }
                for checkin in checkin_rows
            ],
        }

    @staticmethod
    def _insert_task_item(db, entry_id, item, now, active=1):
        return db.execute(
            "INSERT INTO task_items(entry_id, label, position, checked, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (entry_id, item["label"], item["position"], 1 if item["checked"] else 0, active, now),
        )

    @staticmethod
    def _write_task(db, entry_id, task, now):
        db.execute(
            "INSERT INTO task_config(entry_id, per_period, period_unit) VALUES (?, ?, ?)",
            (entry_id, task["per_period"], task["period_unit"]),
        )
        for item in task["items"]:
            Storage._insert_task_item(db, entry_id, item, now)

    @staticmethod
    def _reconcile_task(db, entry_id, task, now):
        db.execute(
            "INSERT INTO task_config(entry_id, per_period, period_unit) VALUES (?, ?, ?)"
            " ON CONFLICT(entry_id) DO UPDATE SET per_period=excluded.per_period, period_unit=excluded.period_unit",
            (entry_id, task["per_period"], task["period_unit"]),
        )
        existing = {row["id"]: row["active"] for row in db.execute("SELECT id, active FROM task_items WHERE entry_id=?", (entry_id,))}
        seen = set()
        for item in task["items"]:
            if item["id"] in existing:
                db.execute(
                    "UPDATE task_items SET label=?, position=?, checked=?, active=1 WHERE id=? AND entry_id=?",
                    (item["label"], item["position"], 1 if item["checked"] else 0, item["id"], entry_id),
                )
                seen.add(item["id"])
            else:
                Storage._insert_task_item(db, entry_id, item, now)
        for item_id, active in existing.items():
            if item_id not in seen and active:
                db.execute("UPDATE task_items SET active=0, checked=0 WHERE id=?", (item_id,))

    @staticmethod
    def _import_task(db, entry_id, task, now):
        db.execute(
            "INSERT INTO task_config(entry_id, per_period, period_unit) VALUES (?, ?, ?)",
            (entry_id, task["per_period"], task["period_unit"]),
        )
        id_map = {}
        for item in task["items"]:
            cursor = Storage._insert_task_item(db, entry_id, item, now, 1 if item["active"] else 0)
            if item["id"] is not None:
                id_map[item["id"]] = cursor.lastrowid
        for checkin in task.get("checkins", []):
            source_ids = checkin["checked_item_ids"]
            remapped = [id_map[i] for i in source_ids if i in id_map] if source_ids is not None else None
            db.execute(
                "INSERT INTO task_checkins(entry_id, occurred_at, checked_count, total_count, changed, checked_item_ids) VALUES (?, ?, ?, ?, ?, ?)",
                (entry_id, checkin["occurred_at"], checkin["checked_count"], checkin["total_count"],
                 1 if checkin["changed"] else 0, json.dumps(remapped) if remapped is not None else None),
            )

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.isolation_level = None
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            connection.execute("COMMIT")
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = int(path.name.split("_", 1)[0])
                if version in applied:
                    continue
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _sql_statements(path.read_text(encoding="utf-8")):
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, self._now()),
                    )
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        finally:
            connection.close()

    def list_trackers(self):
        with self._connect() as db:
            return self._assemble_trackers(db)

    def get_tracker(self, tracker_id):
        with self._connect() as db:
            trackers = self._assemble_trackers(db, tracker_id)
        return trackers[0] if trackers else None

    def _assemble_trackers(self, db, tracker_id=None):
        if tracker_id is None:
            trackers = [dict(row) for row in db.execute("SELECT * FROM trackers ORDER BY id")]
            entries = [dict(row) for row in db.execute("SELECT * FROM entries ORDER BY id")]
            configs = {row["entry_id"]: dict(row) for row in db.execute("SELECT * FROM task_config")}
            item_rows = [dict(row) for row in db.execute("SELECT * FROM task_items ORDER BY entry_id, position, id")]
            checkin_rows = [dict(row) for row in db.execute("SELECT * FROM task_checkins ORDER BY entry_id, id")]
        else:
            trackers = [dict(row) for row in db.execute("SELECT * FROM trackers WHERE id=?", (tracker_id,))]
            entries = [dict(row) for row in db.execute(
                "SELECT * FROM entries WHERE tracker_id=? ORDER BY id", (tracker_id,)
            )]
            entry_ids = [entry["id"] for entry in entries]
            if entry_ids:
                placeholders = ",".join("?" * len(entry_ids))
                configs = {
                    row["entry_id"]: dict(row)
                    for row in db.execute(f"SELECT * FROM task_config WHERE entry_id IN ({placeholders})", entry_ids)
                }
                item_rows = [dict(row) for row in db.execute(
                    f"SELECT * FROM task_items WHERE entry_id IN ({placeholders}) ORDER BY entry_id, position, id",
                    entry_ids,
                )]
                checkin_rows = [dict(row) for row in db.execute(
                    f"SELECT * FROM task_checkins WHERE entry_id IN ({placeholders}) ORDER BY entry_id, id",
                    entry_ids,
                )]
            else:
                configs, item_rows, checkin_rows = {}, [], []
        items_by = {}
        for item in item_rows:
            items_by.setdefault(item["entry_id"], []).append(item)
        checkins_by = {}
        for checkin in checkin_rows:
            checkins_by.setdefault(checkin["entry_id"], []).append(checkin)
        grouped = {tracker["id"]: [] for tracker in trackers}
        started = {tracker["id"]: tracker["started_at"] for tracker in trackers}
        for entry in entries:
            entry["task"] = self._overlay(
                configs.get(entry["id"]),
                items_by.get(entry["id"], []),
                checkins_by.get(entry["id"], []),
            )
            self._decorate_entry(entry, started.get(entry["tracker_id"]))
            grouped.get(entry["tracker_id"], []).append(entry)
        for tracker in trackers:
            tracker["entries"] = grouped[tracker["id"]]
        return trackers

    def export(self):
        return {"version": 1, "exported_at": self._now(), "trackers": self.list_trackers()}

    def import_data(self, trackers, mode):
        now = self._now()
        counts = {"trackers": 0, "entries": 0}
        with self._connect() as db:
            if mode == "replace":
                db.execute("DELETE FROM trackers")
            for tracker in trackers:
                cursor = db.execute(
                    "INSERT INTO trackers(title, description, started_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (tracker["title"], tracker["description"], tracker["started_at"], now, now),
                )
                tracker_id = cursor.lastrowid
                counts["trackers"] += 1
                for entry in tracker["entries"]:
                    values = tuple(entry[key] for key in ENTRY_FIELDS)
                    cursor = db.execute(
                        "INSERT INTO entries(tracker_id,kind,title,body,occurred_at,target_mode,target_at,target_value,target_unit,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (tracker_id, *values, now, now),
                    )
                    counts["entries"] += 1
                    if entry.get("task"):
                        self._import_task(db, cursor.lastrowid, entry["task"], now)
        return counts

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
            return self._load_entry(db, entry_id)

    @staticmethod
    def _load_entry(db, entry_id):
        row = db.execute(
            "SELECT entries.*, trackers.started_at AS tracker_started_at "
            "FROM entries JOIN trackers ON trackers.id = entries.tracker_id WHERE entries.id=?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return None
        entry = dict(row)
        started_at = entry.pop("tracker_started_at")
        config = Storage._dict(db.execute("SELECT * FROM task_config WHERE entry_id=?", (entry_id,)).fetchone())
        item_rows = [dict(r) for r in db.execute(
            "SELECT * FROM task_items WHERE entry_id=? ORDER BY position, id", (entry_id,)
        )]
        checkin_rows = [dict(r) for r in db.execute(
            "SELECT * FROM task_checkins WHERE entry_id=? ORDER BY id", (entry_id,)
        )]
        entry["task"] = Storage._overlay(config, item_rows, checkin_rows)
        return Storage._decorate_entry(entry, started_at)

    @staticmethod
    def _decorate_entry(entry, started_at):
        if entry.get("kind") == "milestone":
            try:
                entry["resolved_target_at"] = resolve_milestone_target(started_at, entry)
            except (ValidationError, KeyError, TypeError):
                entry["resolved_target_at"] = None
        else:
            entry["resolved_target_at"] = None
        return entry

    def create_entry(self, tracker_id, data):
        now = self._now()
        values = tuple(data[key] for key in ENTRY_FIELDS)
        with self._connect() as db:
            if db.execute("SELECT 1 FROM trackers WHERE id=?", (tracker_id,)).fetchone() is None:
                return None
            cursor = db.execute(
                "INSERT INTO entries(tracker_id,kind,title,body,occurred_at,target_mode,target_at,target_value,target_unit,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (tracker_id, *values, now, now),
            )
            entry_id = cursor.lastrowid
            if data.get("task"):
                self._write_task(db, entry_id, data["task"], now)
            db.execute("UPDATE trackers SET updated_at=? WHERE id=?", (now, tracker_id))
        return self.get_entry(entry_id)

    def update_entry(self, entry_id, data):
        now = self._now()
        values = tuple(data[key] for key in ENTRY_FIELDS)
        try:
            with self._connect(immediate=True) as db:
                row = db.execute("SELECT tracker_id FROM entries WHERE id=?", (entry_id,)).fetchone()
                if row is None:
                    return None
                db.execute(
                    "UPDATE entries SET kind=?,title=?,body=?,occurred_at=?,target_mode=?,target_at=?,target_value=?,target_unit=?,updated_at=? WHERE id=?",
                    (*values, now, entry_id),
                )
                if data.get("task"):
                    self._reconcile_task(db, entry_id, data["task"], now)
                elif "task" in data and data["task"] is None:
                    db.execute("DELETE FROM task_checkins WHERE entry_id=?", (entry_id,))
                    db.execute("DELETE FROM task_items WHERE entry_id=?", (entry_id,))
                    db.execute("DELETE FROM task_config WHERE entry_id=?", (entry_id,))
                db.execute("UPDATE trackers SET updated_at=? WHERE id=?", (now, row["tracker_id"]))
        except sqlite3.IntegrityError:
            return None
        return self.get_entry(entry_id)

    def create_checkin(self, entry_id):
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat().replace("+00:00", "Z")
        occurred_at = int(now_dt.timestamp())
        try:
            with self._connect(immediate=True) as db:
                entry = self._load_entry(db, entry_id)
                if entry is None or entry["kind"] != "milestone" or not entry.get("task"):
                    return None
                items = [item for item in entry["task"]["items"] if item["active"]]
                checked_ids = sorted(item["id"] for item in items if item["checked"])
                total = len(items)
                last_changed = db.execute(
                    "SELECT checked_item_ids, total_count FROM task_checkins WHERE entry_id=? AND changed=1 ORDER BY id DESC LIMIT 1",
                    (entry_id,),
                ).fetchone()
                if last_changed is None:
                    changed = True
                else:
                    previous = set(json.loads(last_changed["checked_item_ids"] or "[]"))
                    changed = set(checked_ids) != previous or total != last_changed["total_count"]
                cursor = db.execute(
                    "INSERT INTO task_checkins(entry_id, occurred_at, checked_count, total_count, changed, checked_item_ids) VALUES (?, ?, ?, ?, ?, ?)",
                    (entry_id, occurred_at, len(checked_ids), total, 1 if changed else 0, json.dumps(checked_ids)),
                )
                db.execute("UPDATE trackers SET updated_at=? WHERE id=?", (now, entry["tracker_id"]))
                checkin_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return None
        return {
            "id": checkin_id, "entry_id": entry_id, "occurred_at": occurred_at,
            "checked_count": len(checked_ids), "total_count": total,
            "changed": changed, "checked_item_ids": checked_ids,
        }

    def update_task_item_checked(self, entry_id, item_id, checked):
        try:
            with self._connect(immediate=True) as db:
                row = db.execute(
                    "SELECT task_items.id, entries.tracker_id FROM task_items "
                    "JOIN entries ON entries.id = task_items.entry_id "
                    "WHERE task_items.id=? AND task_items.entry_id=? AND task_items.active=1",
                    (item_id, entry_id),
                ).fetchone()
                if row is None:
                    return None
                db.execute("UPDATE task_items SET checked=? WHERE id=?", (1 if checked else 0, item_id))
                db.execute("UPDATE trackers SET updated_at=? WHERE id=?", (self._now(), row["tracker_id"]))
        except sqlite3.IntegrityError:
            return None
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
