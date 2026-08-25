-- Allow task-only milestones (target_mode 'none') and add the task overlay tables.
ALTER TABLE entries RENAME TO entries_without_tasks;

CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('note', 'milestone')),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    body TEXT NOT NULL DEFAULT '' CHECK(length(body) <= 2000),
    occurred_at TEXT,
    target_mode TEXT CHECK(target_mode IN ('date', 'duration', 'none') OR target_mode IS NULL),
    target_at TEXT,
    target_value REAL,
    target_unit TEXT CHECK(target_unit IN ('hours', 'days', 'weeks', 'four_weeks', 'months', 'years') OR target_unit IS NULL),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO entries SELECT * FROM entries_without_tasks;
DROP TABLE entries_without_tasks;
CREATE INDEX entries_tracker_id_idx ON entries(tracker_id);

CREATE TABLE task_config (
    entry_id INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    per_period INTEGER NOT NULL CHECK(per_period >= 1),
    period_unit TEXT NOT NULL CHECK(period_unit IN ('day', 'week'))
);

CREATE TABLE task_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 120),
    position INTEGER NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE task_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    occurred_at INTEGER NOT NULL,
    checked_count INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    changed INTEGER NOT NULL,
    checked_item_ids TEXT
);

CREATE INDEX task_items_entry_id_idx ON task_items(entry_id);
CREATE INDEX task_checkins_entry_id_idx ON task_checkins(entry_id);
