-- Add 'four_weeks' (a 28-day month) to the allowed milestone duration units.
-- SQLite cannot alter a CHECK constraint in place, so the entries table is rebuilt.
ALTER TABLE entries RENAME TO entries_without_four_weeks;

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
    target_unit TEXT CHECK(target_unit IN ('hours', 'days', 'weeks', 'four_weeks', 'months', 'years') OR target_unit IS NULL),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO entries SELECT * FROM entries_without_four_weeks;
DROP TABLE entries_without_four_weeks;
CREATE INDEX entries_tracker_id_idx ON entries(tracker_id);
