import unittest

from domain import ValidationError, resolve_milestone_target, validate_entry, validate_tracker


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
