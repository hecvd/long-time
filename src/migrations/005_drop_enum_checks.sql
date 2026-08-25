-- Domain validation owns vocabularies. Enum CHECKs forced a full table rebuild
-- for every new unit. Keep structural constraints only.
CREATE TABLE entries_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    body TEXT NOT NULL DEFAULT '' CHECK(length(body) <= 2000),
    occurred_at TEXT,
    target_mode TEXT,
    target_at TEXT,
    target_value REAL,
    target_unit TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO entries_new SELECT * FROM entries;

CREATE TABLE task_config_new (
    entry_id INTEGER PRIMARY KEY REFERENCES entries_new(id) ON DELETE CASCADE,
    per_period INTEGER NOT NULL CHECK(per_period >= 1),
    period_unit TEXT NOT NULL
);
INSERT INTO task_config_new SELECT * FROM task_config;

CREATE TABLE task_items_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries_new(id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 120),
    position INTEGER NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
INSERT INTO task_items_new SELECT * FROM task_items;

CREATE TABLE task_checkins_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries_new(id) ON DELETE CASCADE,
    occurred_at INTEGER NOT NULL,
    checked_count INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    changed INTEGER NOT NULL,
    checked_item_ids TEXT
);
INSERT INTO task_checkins_new SELECT * FROM task_checkins;

DROP TABLE task_checkins;
DROP TABLE task_items;
DROP TABLE task_config;
DROP TABLE entries;

ALTER TABLE entries_new RENAME TO entries;
ALTER TABLE task_config_new RENAME TO task_config;
ALTER TABLE task_items_new RENAME TO task_items;
ALTER TABLE task_checkins_new RENAME TO task_checkins;

CREATE INDEX entries_tracker_id_idx ON entries(tracker_id);
CREATE INDEX task_items_entry_id_idx ON task_items(entry_id);
CREATE INDEX task_checkins_entry_id_idx ON task_checkins(entry_id);
