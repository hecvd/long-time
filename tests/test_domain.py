import unittest

from domain import (
    ValidationError,
    resolve_milestone_target,
    unit_catalog,
    validate_entry,
    validate_import,
    validate_task_item_checked,
    validate_tracker,
)


class DomainTestCase(unittest.TestCase):
    def test_validate_tracker_normalizes_timestamp_to_utc(self):
        value = validate_tracker({"title": "  Learning piano  ", "description": " daily ", "started_at": "2023-11-16T18:30:00+01:00"})
        self.assertEqual(value, {"title": "Learning piano", "description": "daily", "started_at": "2023-11-16T17:30:00Z"})

    def test_tracker_requires_valid_fields(self):
        with self.assertRaises(ValidationError) as context:
            validate_tracker({"title": "", "description": "x" * 501, "started_at": "2024-01-01"})
        self.assertEqual(set(context.exception.fields), {"title", "description", "started_at"})

    def test_note_normalizes_and_rejects_target_fields(self):
        note = validate_entry({"kind": "note", "title": " Now ", "body": " ok ", "occurred_at": "2024-01-01T01:00:00+01:00"})
        self.assertEqual(note["occurred_at"], "2024-01-01T00:00:00Z")
        with self.assertRaises(ValidationError):
            validate_entry({**note, "target_mode": "date"})

    def test_duration_milestone_rejects_date_fields(self):
        with self.assertRaises(ValidationError) as context:
            validate_entry({"kind": "milestone", "title": "Three years", "body": "", "target_mode": "duration", "target_value": 3, "target_unit": "years", "target_at": "2026-11-16T17:30:00Z"})
        self.assertIn("target_at", context.exception.fields)

    def test_calendar_year_from_leap_day_uses_february_28(self):
        target = resolve_milestone_target("2024-02-29T10:15:00Z", {"target_mode": "duration", "target_value": 1, "target_unit": "years"})
        self.assertEqual(target, "2025-02-28T10:15:00Z")

    def test_duration_units_resolve(self):
        target = resolve_milestone_target("2024-01-01T00:00:00Z", {"target_mode": "duration", "target_value": 2, "target_unit": "weeks"})
        self.assertEqual(target, "2024-01-15T00:00:00Z")

    def test_calendar_months_resolve_at_month_end_and_across_years(self):
        leap_target = resolve_milestone_target(
            "2024-01-31T10:15:00Z",
            {"target_mode": "duration", "target_value": 1, "target_unit": "months"},
        )
        crossing_target = resolve_milestone_target(
            "2024-11-30T10:15:00Z",
            {"target_mode": "duration", "target_value": 3, "target_unit": "months"},
        )
        self.assertEqual(leap_target, "2024-02-29T10:15:00Z")
        self.assertEqual(crossing_target, "2025-02-28T10:15:00Z")

    def test_four_week_months_resolve_as_28_days_and_allow_fractions(self):
        whole = resolve_milestone_target(
            "2024-01-01T00:00:00Z",
            {"target_mode": "duration", "target_value": 1, "target_unit": "four_weeks"},
        )
        fractional = resolve_milestone_target(
            "2024-01-01T00:00:00Z",
            {"target_mode": "duration", "target_value": 1.5, "target_unit": "four_weeks"},
        )
        self.assertEqual(whole, "2024-01-29T00:00:00Z")
        self.assertEqual(fractional, "2024-02-12T00:00:00Z")
        accepted = validate_entry({
            "kind": "milestone", "title": "Six weeks", "body": "",
            "target_mode": "duration", "target_value": 1.5, "target_unit": "four_weeks",
        })
        self.assertEqual(accepted["target_value"], 1.5)

    def test_validate_import_normalizes_trackers_and_entries(self):
        mode, trackers = validate_import({
            "mode": "replace",
            "trackers": [{
                "title": " Piano ", "description": "", "started_at": "2024-01-01T00:00:00Z",
                "entries": [{
                    "kind": "note", "title": "Started", "body": "",
                    "occurred_at": "2024-02-01T00:00:00Z",
                }],
            }],
        })
        self.assertEqual(mode, "replace")
        self.assertEqual(trackers[0]["title"], "Piano")
        self.assertEqual(trackers[0]["entries"][0]["kind"], "note")

    def test_validate_import_requires_valid_mode_and_list(self):
        with self.assertRaises(ValidationError) as raised:
            validate_import({"mode": "merge", "trackers": []})
        self.assertIn("mode", raised.exception.fields)
        with self.assertRaises(ValidationError):
            validate_import({"mode": "append", "trackers": "nope"})

    def test_validate_import_namespaces_nested_errors(self):
        with self.assertRaises(ValidationError) as raised:
            validate_import({
                "mode": "append",
                "trackers": [{
                    "title": "OK", "description": "", "started_at": "2024-01-01T00:00:00Z",
                    "entries": [{"kind": "note", "title": "", "occurred_at": "2024-01-01T00:00:00Z"}],
                }],
            })
        self.assertIn("trackers[0].entries[0].title", raised.exception.fields)

    def test_validate_import_skips_checkins_with_invalid_counts(self):
        _, trackers = validate_import({
            "mode": "replace",
            "trackers": [{
                "title": "Piano", "description": "", "started_at": "2024-01-01T00:00:00Z",
                "entries": [{
                    "kind": "milestone", "title": "M", "body": "", "target_mode": "none",
                    "task": {
                        "per_period": 1, "period_unit": "day",
                        "items": [{"label": "A"}],
                        "checkins": [
                            {"occurred_at": 1, "checked_count": "nope", "total_count": 1, "changed": True},
                            {"occurred_at": 2, "checked_count": 1, "total_count": 1, "changed": True},
                        ],
                    },
                }],
            }],
        })
        self.assertEqual(len(trackers[0]["entries"][0]["task"]["checkins"]), 1)
        self.assertEqual(trackers[0]["entries"][0]["task"]["checkins"][0]["occurred_at"], 2)

    def test_calendar_months_require_whole_numbers(self):
        valid = validate_entry({
            "kind": "milestone", "title": "One month", "body": "",
            "target_mode": "duration", "target_value": 1, "target_unit": "months",
        })
        self.assertEqual(valid["target_unit"], "months")
        with self.assertRaises(ValidationError) as raised:
            validate_entry({
                "kind": "milestone", "title": "Half month", "body": "",
                "target_mode": "duration", "target_value": 0.5, "target_unit": "months",
            })
        self.assertIn("whole number", raised.exception.fields["target_value"])

    def test_task_only_milestone_validates(self):
        result = validate_entry({
            "kind": "milestone", "title": "Morning routine", "body": "", "target_mode": "none",
            "task": {"per_period": 1, "period_unit": "day",
                     "items": [{"label": "Push-ups", "checked": True}, {"id": 4, "label": "Read"}]},
        })
        self.assertEqual(result["target_mode"], "none")
        self.assertEqual(result["task"]["per_period"], 1)
        self.assertEqual(result["task"]["items"][0], {"id": None, "label": "Push-ups", "checked": True, "position": 0})
        self.assertEqual(result["task"]["items"][1], {"id": 4, "label": "Read", "checked": False, "position": 1})

    def test_milestone_with_neither_target_nor_task_is_rejected(self):
        with self.assertRaises(ValidationError) as raised:
            validate_entry({"kind": "milestone", "title": "Empty", "body": "", "target_mode": "none"})
        self.assertIn("task", raised.exception.fields)

    def test_note_rejects_task_field(self):
        with self.assertRaises(ValidationError) as raised:
            validate_entry({"kind": "note", "title": "N", "body": "", "occurred_at": "2024-01-01T00:00:00Z",
                            "task": {"per_period": 1, "period_unit": "day", "items": [{"label": "x"}]}})
        self.assertIn("task", raised.exception.fields)

    def test_task_cadence_and_unit_bounds(self):
        with self.assertRaises(ValidationError) as raised:
            validate_entry({"kind": "milestone", "title": "M", "body": "", "target_mode": "none",
                            "task": {"per_period": 0, "period_unit": "month", "items": [{"label": "x"}]}})
        self.assertIn("task.per_period", raised.exception.fields)
        self.assertIn("task.period_unit", raised.exception.fields)
        self.assertNotIn("task", raised.exception.fields)

    def test_task_requires_a_labeled_item(self):
        with self.assertRaises(ValidationError) as raised:
            validate_entry({"kind": "milestone", "title": "M", "body": "", "target_mode": "none",
                            "task": {"per_period": 1, "period_unit": "day", "items": [{"label": "  "}]}})
        self.assertIn("task.items[0].label", raised.exception.fields)

    def test_deadline_and_task_can_coexist(self):
        result = validate_entry({
            "kind": "milestone", "title": "Both", "body": "", "target_mode": "duration",
            "target_value": 3, "target_unit": "years",
            "task": {"per_period": 2, "period_unit": "week", "items": [{"label": "x"}]}})
        self.assertEqual(result["target_unit"], "years")
        self.assertEqual(result["task"]["period_unit"], "week")

    def test_validate_import_accepts_cumulative_items_over_the_interactive_cap(self):
        items = [{"label": f"a{i}", "active": True} for i in range(60)]
        items.extend({"label": f"r{i}", "active": False} for i in range(41))
        _, trackers = validate_import({
            "mode": "replace",
            "trackers": [{
                "title": "Piano", "description": "", "started_at": "2024-01-01T00:00:00Z",
                "entries": [{
                    "kind": "milestone", "title": "M", "body": "", "target_mode": "none",
                    "task": {"per_period": 2000, "period_unit": "fortnight", "items": items},
                }],
            }],
        })
        task = trackers[0]["entries"][0]["task"]
        self.assertEqual(len(task["items"]), 101)
        self.assertEqual(sum(1 for item in task["items"] if item["active"]), 60)
        self.assertEqual(task["per_period"], 2000)
        self.assertEqual(task["period_unit"], "day")

    def test_validate_import_skips_out_of_range_checkin_numbers(self):
        _, trackers = validate_import({
            "mode": "replace",
            "trackers": [{
                "title": "Piano", "description": "", "started_at": "2024-01-01T00:00:00Z",
                "entries": [{
                    "kind": "milestone", "title": "M", "body": "", "target_mode": "none",
                    "task": {
                        "per_period": 1, "period_unit": "day",
                        "items": [{"label": "A"}],
                        "checkins": [
                            {"occurred_at": 10**20, "checked_count": 1, "total_count": 1, "changed": True},
                            {"occurred_at": 2, "checked_count": 1, "total_count": 1, "changed": True, "checked_item_ids": [1]},
                            {"occurred_at": 3, "checked_count": 100_001, "total_count": 1, "changed": True},
                        ],
                    },
                }],
            }],
        })
        checkins = trackers[0]["entries"][0]["task"]["checkins"]
        self.assertEqual(len(checkins), 1)
        self.assertEqual(checkins[0]["occurred_at"], 2)

    def test_validate_import_downgrades_changed_checkins_without_snapshots(self):
        _, trackers = validate_import({
            "mode": "replace",
            "trackers": [{
                "title": "Piano", "description": "", "started_at": "2024-01-01T00:00:00Z",
                "entries": [{
                    "kind": "milestone", "title": "M", "body": "", "target_mode": "none",
                    "task": {
                        "per_period": 1, "period_unit": "day",
                        "items": [{"label": "A"}],
                        "checkins": [
                            {"occurred_at": 1, "checked_count": 0, "total_count": 1, "changed": True, "checked_item_ids": None},
                        ],
                    },
                }],
            }],
        })
        checkin = trackers[0]["entries"][0]["task"]["checkins"][0]
        self.assertFalse(checkin["changed"])

    def test_validate_entry_omits_task_when_the_key_is_absent(self):
        result = validate_entry({
            "kind": "milestone", "title": "Rename", "body": "",
            "target_mode": "duration", "target_value": 1, "target_unit": "years",
        })
        self.assertNotIn("task", result)

    def test_updating_task_only_milestone_may_omit_task(self):
        result = validate_entry({
            "kind": "milestone", "title": "Rename", "body": "", "target_mode": "none",
        }, updating=True)
        self.assertNotIn("task", result)
        self.assertEqual(result["target_mode"], "none")

    def test_task_only_milestone_resolves_to_tracker_start(self):
        target = resolve_milestone_target("2024-01-01T10:00:00Z", {"target_mode": "none"})
        self.assertEqual(target, "2024-01-01T10:00:00Z")

    def test_calendar_years_out_of_range_are_rejected(self):
        with self.assertRaises(ValidationError) as raised:
            resolve_milestone_target(
                "9999-01-01T00:00:00Z",
                {"target_mode": "duration", "target_value": 1, "target_unit": "years"},
            )
        self.assertIn("target_value", raised.exception.fields)

    def test_unit_catalog_lists_duration_and_task_period_units(self):
        catalog = unit_catalog()
        duration_ids = [unit["id"] for unit in catalog["duration_units"]]
        self.assertEqual(duration_ids, ["hours", "days", "weeks", "four_weeks", "months", "years"])
        months = next(unit for unit in catalog["duration_units"] if unit["id"] == "months")
        self.assertTrue(months["whole_only"])
        self.assertEqual(months["kind"], "calendar")
        self.assertEqual([unit["id"] for unit in catalog["task_period_units"]], ["day", "week"])

    def test_validate_task_item_checked_requires_a_boolean(self):
        self.assertTrue(validate_task_item_checked({"checked": True}))
        self.assertFalse(validate_task_item_checked({"checked": False}))
        with self.assertRaises(ValidationError) as raised:
            validate_task_item_checked({"checked": 1})
        self.assertIn("checked", raised.exception.fields)
