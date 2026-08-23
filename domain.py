from __future__ import annotations

import calendar
import math
import re
from datetime import datetime, timedelta, timezone

TIMESTAMP_WITH_ZONE = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")
UNITS = {"hours", "days", "weeks", "months", "years"}


class ValidationError(ValueError):
    def __init__(self, fields: dict[str, str]):
        super().__init__("Validation failed")
        self.fields = fields


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value, field_name: str) -> str:
    if not isinstance(value, str) or not TIMESTAMP_WITH_ZONE.search(value):
        raise ValidationError({field_name: "Enter a date and time with a timezone."})
    try:
        return utc_text(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as error:
        raise ValidationError({field_name: "Enter a valid date and time."}) from error


def _text(payload, name: str, maximum: int, required: bool, fields: dict[str, str]) -> str:
    value = payload.get(name, "")
    value = value.strip() if isinstance(value, str) else ""
    if required and not value:
        fields[name] = "Enter a title."
    elif len(value) > maximum:
        fields[name] = f"Use at most {maximum} characters."
    return value


def validate_tracker(payload) -> dict:
    fields = {}
    title = _text(payload, "title", 120, True, fields)
    description = _text(payload, "description", 500, False, fields)
    try:
        started_at = parse_timestamp(payload.get("started_at"), "started_at")
    except ValidationError as error:
        fields.update(error.fields)
        started_at = None
    if fields:
        raise ValidationError(fields)
    return {"title": title, "description": description, "started_at": started_at}


def validate_entry(payload) -> dict:
    fields = {}
    kind = payload.get("kind")
    title = _text(payload, "title", 120, True, fields)
    body = _text(payload, "body", 2000, False, fields)
    result = {
        "kind": kind, "title": title, "body": body, "occurred_at": None,
        "target_mode": None, "target_at": None, "target_value": None, "target_unit": None,
    }
    if kind not in {"note", "milestone"}:
        fields["kind"] = "Choose note or milestone."
    elif kind == "note":
        try:
            result["occurred_at"] = parse_timestamp(payload.get("occurred_at"), "occurred_at")
        except ValidationError as error:
            fields.update(error.fields)
        for name in ("target_mode", "target_at", "target_value", "target_unit"):
            if payload.get(name) not in (None, ""):
                fields[name] = "Notes cannot contain milestone targets."
    else:
        mode = payload.get("target_mode")
        result["target_mode"] = mode
        if payload.get("occurred_at") not in (None, ""):
            fields["occurred_at"] = "Milestones cannot contain a note timestamp."
        if mode == "date":
            try:
                result["target_at"] = parse_timestamp(payload.get("target_at"), "target_at")
            except ValidationError as error:
                fields.update(error.fields)
            for name in ("target_value", "target_unit"):
                if payload.get(name) not in (None, ""):
                    fields[name] = "Date milestones cannot contain a duration."
        elif mode == "duration":
            value, unit = payload.get("target_value"), payload.get("target_unit")
            valid_number = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            if not valid_number or not 0 < value <= 1_000_000:
                fields["target_value"] = "Enter a positive duration up to 1,000,000."
            elif unit in {"months", "years"} and value % 1 != 0:
                fields["target_value"] = "Calendar months and years must be whole numbers."
            else:
                result["target_value"] = value
            if unit not in UNITS:
                fields["target_unit"] = "Choose hours, days, weeks, months, or years."
            else:
                result["target_unit"] = unit
            if payload.get("target_at") not in (None, ""):
                fields["target_at"] = "Duration milestones cannot contain a target date."
        else:
            fields["target_mode"] = "Choose a date or duration target."
    if fields:
        raise ValidationError(fields)
    return result


def add_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def resolve_milestone_target(started_at: str, entry: dict) -> str:
    if entry.get("target_mode") == "date":
        return parse_timestamp(entry.get("target_at"), "target_at")
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    value, unit = entry["target_value"], entry["target_unit"]
    if unit == "years":
        try:
            target = start.replace(year=start.year + int(value))
        except ValueError:
            target = start.replace(year=start.year + int(value), day=28)
    elif unit == "months":
        try:
            target = add_calendar_months(start, int(value))
        except (OverflowError, ValueError) as error:
            raise ValidationError({"target_value": "The target is outside the supported date range."}) from error
    else:
        hours = value * {"hours": 1, "days": 24, "weeks": 168}[unit]
        target = start + timedelta(hours=hours)
    return utc_text(target)
