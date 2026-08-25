from __future__ import annotations

import calendar
import math
import re
from datetime import UTC, datetime, timedelta

TIMESTAMP_WITH_ZONE = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")
UNITS = {"hours", "days", "weeks", "four_weeks", "months", "years"}
TASK_PERIOD_UNITS = {"day", "week"}
MAX_TASK_ITEMS = 100


class ValidationError(ValueError):
    def __init__(self, fields: dict[str, str]):
        super().__init__("Validation failed")
        self.fields = fields


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value, field_name: str) -> str:
    if not isinstance(value, str) or not TIMESTAMP_WITH_ZONE.search(value):
        raise ValidationError({field_name: "Enter a date and time with a timezone."})
    try:
        return utc_text(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as error:
        raise ValidationError({field_name: "Enter a valid date and time."}) from error


def _int_id(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


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


def validate_task(raw, fields: dict[str, str]):
    if raw in (None, ""):
        return None
    if not isinstance(raw, dict):
        fields["task"] = "Provide a checklist object."
        return None
    initial_keys = set(fields.keys())
    items_raw = raw.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        fields["task.items"] = "Add at least one checklist item."
        items_raw = []
    elif len(items_raw) > MAX_TASK_ITEMS:
        fields["task.items"] = f"Use at most {MAX_TASK_ITEMS} items."
        items_raw = []
    items = []
    for index, raw_item in enumerate(items_raw):
        if not isinstance(raw_item, dict):
            fields[f"task.items[{index}]"] = "Each item must be an object."
            continue
        label = raw_item.get("label")
        label = label.strip() if isinstance(label, str) else ""
        if not label:
            fields[f"task.items[{index}].label"] = "Enter a label."
        elif len(label) > 120:
            fields[f"task.items[{index}].label"] = "Use at most 120 characters."
        items.append({
            "id": _int_id(raw_item.get("id")), "label": label,
            "checked": bool(raw_item.get("checked")), "position": index,
        })
    per_period = raw.get("per_period")
    if not (isinstance(per_period, int) and not isinstance(per_period, bool) and 1 <= per_period <= 1000):
        fields["task.per_period"] = "Enter how many check-ins per period (1 or more)."
    if raw.get("period_unit") not in TASK_PERIOD_UNITS:
        fields["task.period_unit"] = "Choose day or week."
    if set(fields.keys()) != initial_keys:
        return None
    return {"per_period": per_period, "period_unit": raw.get("period_unit"), "items": items}


def validate_import_task(raw):
    if not isinstance(raw, dict):
        return None
    items = []
    for index, raw_item in enumerate(raw.get("items") or []):
        if not isinstance(raw_item, dict):
            continue
        label = raw_item.get("label")
        label = label.strip() if isinstance(label, str) else ""
        if not label:
            continue
        position = raw_item.get("position")
        items.append({
            "id": _int_id(raw_item.get("id")), "label": label[:120],
            "position": position if isinstance(position, int) and not isinstance(position, bool) else index,
            "checked": bool(raw_item.get("checked")), "active": bool(raw_item.get("active", True)),
        })
    if not items:
        return None
    per_period = raw.get("per_period")
    per_period = per_period if isinstance(per_period, int) and not isinstance(per_period, bool) and per_period >= 1 else 1
    unit = raw.get("period_unit") if raw.get("period_unit") in TASK_PERIOD_UNITS else "day"
    checkins = []
    for raw_checkin in raw.get("checkins") or []:
        if not isinstance(raw_checkin, dict):
            continue
        occurred = raw_checkin.get("occurred_at")
        if not (isinstance(occurred, int) and not isinstance(occurred, bool)):
            continue
        raw_ids = raw_checkin.get("checked_item_ids")
        checked_ids = (
            [i for i in raw_ids if isinstance(i, int) and not isinstance(i, bool)]
            if isinstance(raw_ids, list) else None
        )
        try:
            checked_count = int(raw_checkin.get("checked_count") or 0)
            total_count = int(raw_checkin.get("total_count") or 0)
        except (TypeError, ValueError):
            continue
        checkins.append({
            "occurred_at": occurred,
            "checked_count": checked_count,
            "total_count": total_count,
            "changed": bool(raw_checkin.get("changed")),
            "checked_item_ids": checked_ids,
        })
    return {"per_period": per_period, "period_unit": unit, "items": items, "checkins": checkins}


def validate_entry(payload) -> dict:
    fields = {}
    kind = payload.get("kind")
    title = _text(payload, "title", 120, True, fields)
    body = _text(payload, "body", 2000, False, fields)
    result = {
        "kind": kind, "title": title, "body": body, "occurred_at": None,
        "target_mode": None, "target_at": None, "target_value": None, "target_unit": None,
        "task": None,
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
        if payload.get("task") not in (None, ""):
            fields["task"] = "Notes cannot contain a checklist."
    else:
        mode = payload.get("target_mode")
        result["task"] = validate_task(payload.get("task"), fields)
        if payload.get("occurred_at") not in (None, ""):
            fields["occurred_at"] = "Milestones cannot contain a note timestamp."
        if mode == "date":
            result["target_mode"] = "date"
            try:
                result["target_at"] = parse_timestamp(payload.get("target_at"), "target_at")
            except ValidationError as error:
                fields.update(error.fields)
            for name in ("target_value", "target_unit"):
                if payload.get(name) not in (None, ""):
                    fields[name] = "Date milestones cannot contain a duration."
        elif mode == "duration":
            result["target_mode"] = "duration"
            value, unit = payload.get("target_value"), payload.get("target_unit")
            valid_number = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            if not valid_number or not 0 < value <= 1_000_000:
                fields["target_value"] = "Enter a positive duration up to 1,000,000."
            elif unit in {"months", "years"} and value % 1 != 0:
                fields["target_value"] = "Calendar months and years must be whole numbers."
            else:
                result["target_value"] = value
            if unit not in UNITS:
                fields["target_unit"] = "Choose hours, days, weeks, four-week months, calendar months, or years."
            else:
                result["target_unit"] = unit
            if payload.get("target_at") not in (None, ""):
                fields["target_at"] = "Duration milestones cannot contain a target date."
        elif mode == "none":
            result["target_mode"] = "none"
            for name in ("target_at", "target_value", "target_unit"):
                if payload.get(name) not in (None, ""):
                    fields[name] = "Task-only milestones cannot contain a time target."
            if payload.get("task") in (None, ""):
                fields["task"] = "Add at least one checklist item or choose a deadline."
        else:
            fields["target_mode"] = "Choose a date, duration, or task target."
    if fields:
        raise ValidationError(fields)
    return result


def _prefixed(prefix: str, error: ValidationError) -> dict[str, str]:
    return {f"{prefix}.{key}": message for key, message in error.fields.items()}


def validate_import(payload) -> tuple[str, list[dict]]:
    if not isinstance(payload, dict):
        raise ValidationError({"import": "Provide an import object."})
    mode = payload.get("mode")
    if mode not in {"append", "replace"}:
        raise ValidationError({"mode": "Choose append or replace."})
    raw_trackers = payload.get("trackers")
    if not isinstance(raw_trackers, list):
        raise ValidationError({"trackers": "Provide a list of trackers."})
    trackers = []
    for index, raw in enumerate(raw_trackers):
        prefix = f"trackers[{index}]"
        if not isinstance(raw, dict):
            raise ValidationError({prefix: "Each tracker must be an object."})
        try:
            tracker = validate_tracker(raw)
        except ValidationError as error:
            raise ValidationError(_prefixed(prefix, error)) from error
        raw_entries = raw.get("entries", [])
        if not isinstance(raw_entries, list):
            raise ValidationError({f"{prefix}.entries": "Entries must be a list."})
        entries = []
        for entry_index, raw_entry in enumerate(raw_entries):
            entry_prefix = f"{prefix}.entries[{entry_index}]"
            if not isinstance(raw_entry, dict):
                raise ValidationError({entry_prefix: "Each entry must be an object."})
            try:
                entry = validate_entry(raw_entry)
            except ValidationError as error:
                raise ValidationError(_prefixed(entry_prefix, error)) from error
            if isinstance(raw_entry.get("task"), dict):
                entry["task"] = validate_import_task(raw_entry["task"])
            entries.append(entry)
        tracker["entries"] = entries
        trackers.append(tracker)
    return mode, trackers


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
        hours = value * {"hours": 1, "days": 24, "weeks": 168, "four_weeks": 672}[unit]
        target = start + timedelta(hours=hours)
    return utc_text(target)
