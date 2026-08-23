((root, factory) => {
	const api = factory();
	if (typeof module === "object" && module.exports) module.exports = api;
	else root.LongTimeLogic = api;
})(globalThis, () => {
	const DAY_MS = 86_400_000;
	const YEAR_DAYS = 365.2425;

	function elapsedParts(startedAt, now = new Date()) {
		const difference = now.getTime() - new Date(startedAt).getTime();
		const days = Math.abs(difference) / DAY_MS;
		return {
			future: difference < 0,
			hours: Math.floor(days * 24),
			days: Math.floor(days),
			weeks: Math.round((days / 7) * 10) / 10,
			years: Math.round((days / YEAR_DAYS) * 100) / 100,
		};
	}

	function filterTrackers(trackers, query) {
		const needle = query.trim().toLocaleLowerCase();
		if (!needle) return trackers.slice();
		return trackers.filter((tracker) =>
			[
				tracker.title,
				tracker.description,
				...(tracker.entries || []).flatMap((entry) => [
					entry.title,
					entry.body,
				]),
			].some((value) =>
				String(value || "")
					.toLocaleLowerCase()
					.includes(needle),
			),
		);
	}

	function sortTrackers(trackers, mode) {
		const result = trackers.slice();
		const comparators = {
			recent: (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
			"start-asc": (a, b) =>
				Date.parse(a.started_at) - Date.parse(b.started_at),
			"start-desc": (a, b) =>
				Date.parse(b.started_at) - Date.parse(a.started_at),
			"name-asc": (a, b) =>
				a.title.localeCompare(b.title, undefined, { sensitivity: "base" }),
			"name-desc": (a, b) =>
				b.title.localeCompare(a.title, undefined, { sensitivity: "base" }),
		};
		return result.sort(comparators[mode] || comparators.recent);
	}

	function addCalendarYears(value, years) {
		const target = new Date(value);
		const wantedMonth = target.getUTCMonth();
		target.setUTCFullYear(target.getUTCFullYear() + years);
		if (target.getUTCMonth() !== wantedMonth) target.setUTCDate(0);
		return target;
	}

	function addCalendarMonths(value, months) {
		const target = new Date(value);
		const wantedDay = target.getUTCDate();
		target.setUTCDate(1);
		target.setUTCMonth(target.getUTCMonth() + months);
		const destinationMonth = target.getUTCMonth();
		target.setUTCDate(wantedDay);
		if (target.getUTCMonth() !== destinationMonth) target.setUTCDate(0);
		return target;
	}

	function calendarDurationParts(startedAt, now = new Date()) {
		const started = new Date(startedAt);
		const future = started > now;
		const earlier = future ? now : started;
		const later = future ? started : now;

		let years = later.getUTCFullYear() - earlier.getUTCFullYear();
		let cursor = addCalendarYears(earlier, years);
		if (cursor > later) cursor = addCalendarYears(earlier, --years);

		let months =
			(later.getUTCFullYear() - cursor.getUTCFullYear()) * 12 +
			later.getUTCMonth() -
			cursor.getUTCMonth();
		let monthCursor = addCalendarMonths(cursor, months);
		if (monthCursor > later) monthCursor = addCalendarMonths(cursor, --months);

		const remainingHours = Math.floor((later - monthCursor) / 3_600_000);
		return {
			future,
			years,
			months,
			days: Math.floor(remainingHours / 24),
			hours: remainingHours % 24,
		};
	}

	function formatClosestDuration(parts) {
		let value;
		let unit;
		if (parts.years) [value, unit] = [parts.years, "year"];
		else if (parts.months) [value, unit] = [parts.months, "month"];
		else if (parts.days >= 7) [value, unit] = [Math.floor(parts.days / 7), "week"];
		else if (parts.days) [value, unit] = [parts.days, "day"];
		else [value, unit] = [parts.hours, "hour"];
		return `${value} ${unit}${value === 1 ? "" : "s"}`;
	}

	function resolvedMilestoneTarget(tracker, entry) {
		if (entry.target_mode === "date") return new Date(entry.target_at);
		const start = new Date(tracker.started_at);
		const value = Number(entry.target_value);
		if (entry.target_unit === "years") return addCalendarYears(start, value);
		if (entry.target_unit === "months") return addCalendarMonths(start, value);
		const multipliers = { hours: 3_600_000, days: DAY_MS, weeks: 7 * DAY_MS };
		return new Date(start.getTime() + value * multipliers[entry.target_unit]);
	}

	function milestoneState(tracker, entry, now = new Date()) {
		const target = resolvedMilestoneTarget(tracker, entry);
		return {
			target,
			future: target.getTime() > now.getTime(),
			differenceMs: Math.abs(target - now),
		};
	}

	function entryTimestamp(tracker, entry) {
		if (entry.kind === "note") return new Date(entry.occurred_at);
		return resolvedMilestoneTarget(tracker, entry);
	}

	function orderedEntries(tracker) {
		return (tracker.entries || []).slice().sort((a, b) => {
			const difference =
				entryTimestamp(tracker, b) - entryTimestamp(tracker, a);
			return difference || a.id - b.id;
		});
	}

	function conciseDuration(milliseconds) {
		const hours = milliseconds / 3_600_000;
		if (hours < 48) return `${Math.round(hours * 10) / 10} hours`;
		const days = hours / 24;
		if (days < 14) return `${Math.round(days * 10) / 10} days`;
		const weeks = days / 7;
		if (weeks < 52) return `${Math.round(weeks * 10) / 10} weeks`;
		return `${Math.round((days / YEAR_DAYS) * 100) / 100} years`;
	}

	function entryTimingLabel(tracker, entry, now = new Date()) {
		const timestamp = entryTimestamp(tracker, entry);
		if (entry.kind === "note") {
			const difference = timestamp - new Date(tracker.started_at);
			return `${conciseDuration(Math.abs(difference))} ${difference < 0 ? "before" : "after"} start`;
		}
		const difference = timestamp - now;
		return `${conciseDuration(Math.abs(difference))} ${difference > 0 ? "remaining" : "ago"}`;
	}

	function shouldRefreshOnFocus(lastLoadedAt, now = Date.now()) {
		return now - lastLoadedAt >= 5_000;
	}

	function safePreference(storage, key, fallback, allowedValues) {
		try {
			const value = storage.getItem(key);
			return allowedValues.includes(value) ? value : fallback;
		} catch (_error) {
			return fallback;
		}
	}

	return {
		elapsedParts,
		calendarDurationParts,
		formatClosestDuration,
		filterTrackers,
		sortTrackers,
		resolvedMilestoneTarget,
		milestoneState,
		orderedEntries,
		entryTimingLabel,
		shouldRefreshOnFocus,
		safePreference,
	};
});
