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
    target_unit TEXT CHECK(target_unit IN ('hours', 'days', 'weeks', 'years') OR target_unit IS NULL),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS entries_tracker_id_idx ON entries(tracker_id);
