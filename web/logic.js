((root, factory) => {
	const api = factory();
	if (typeof module === "object" && module.exports) module.exports = api;
	else root.LongTimeLogic = api;
})(globalThis, () => {
	const DAY_MS = 86_400_000;
	const YEAR_DAYS = 365.2425;
	const DATA_CACHE_KEY = "long-time:data";

	function readCachedTrackers(storage) {
		try {
			const parsed = JSON.parse(storage.getItem(DATA_CACHE_KEY));
			return Array.isArray(parsed) ? parsed : [];
		} catch (_error) {
			return [];
		}
	}

	function writeCachedTrackers(storage, trackers) {
		try {
			storage.setItem(DATA_CACHE_KEY, JSON.stringify(trackers));
		} catch (_error) {
			/* ignore quota / unavailable storage */
		}
	}

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
				...(tracker.entries || []).flatMap((entry) => [entry.title, entry.body]),
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
			"start-asc": (a, b) => Date.parse(a.started_at) - Date.parse(b.started_at),
			"start-desc": (a, b) => Date.parse(b.started_at) - Date.parse(a.started_at),
			"name-asc": (a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }),
			"name-desc": (a, b) => b.title.localeCompare(a.title, undefined, { sensitivity: "base" }),
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

		let months = (later.getUTCFullYear() - cursor.getUTCFullYear()) * 12 + later.getUTCMonth() - cursor.getUTCMonth();
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
		if (entry.target_mode === "none") return new Date(tracker.started_at);
		const start = new Date(tracker.started_at);
		const value = Number(entry.target_value);
		if (entry.target_unit === "years") return addCalendarYears(start, value);
		if (entry.target_unit === "months") return addCalendarMonths(start, value);
		const multipliers = {
			hours: 3_600_000,
			days: DAY_MS,
			weeks: 7 * DAY_MS,
			four_weeks: 28 * DAY_MS,
		};
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
			const difference = entryTimestamp(tracker, b) - entryTimestamp(tracker, a);
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

	function periodOrdinal(date, unit) {
		const dayOrdinal = Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / DAY_MS);
		if (unit !== "week") return dayOrdinal;
		const isoDow = (date.getDay() + 6) % 7;
		// Unix day 0 is Thursday, so (dayOrdinal - Monday offset) is never divisible by 7.
		return Math.round((dayOrdinal - isoDow) / 7);
	}

	function taskStats(task, now = new Date()) {
		const checkins = task?.checkins || [];
		const perPeriod = task?.per_period || 1;
		const unit = task?.period_unit || "day";
		const total = checkins.length;
		const last = checkins.reduce((latest, checkin) => {
			if (!latest || checkin.occurred_at > latest.occurred_at) return checkin;
			return latest;
		}, null);
		const latestRate = last ? { checked: last.checked_count, total: last.total_count } : null;

		const counts = new Map();
		for (const checkin of checkins) {
			const ordinal = periodOrdinal(new Date(checkin.occurred_at * 1000), unit);
			counts.set(ordinal, (counts.get(ordinal) || 0) + 1);
		}
		const satisfied = new Set();
		for (const [ordinal, count] of counts) if (count >= perPeriod) satisfied.add(ordinal);

		const nowOrdinal = periodOrdinal(now, unit);
		let currentStreak = 0;
		for (let ordinal = satisfied.has(nowOrdinal) ? nowOrdinal : nowOrdinal - 1; satisfied.has(ordinal); ordinal--)
			currentStreak++;

		let longestStreak = 0;
		let run = 0;
		let previous = null;
		for (const ordinal of [...satisfied].sort((a, b) => a - b)) {
			run = previous !== null && ordinal === previous + 1 ? run + 1 : 1;
			if (run > longestStreak) longestStreak = run;
			previous = ordinal;
		}
		return { currentStreak, longestStreak, total, latestRate };
	}

	function trackerTaskStats(tracker, now = new Date()) {
		const tasks = (tracker.entries || []).filter((entry) => entry.task);
		let checkins = 0;
		let currentStreak = 0;
		for (const entry of tasks) {
			const stats = taskStats(entry.task, now);
			checkins += stats.total;
			if (stats.currentStreak > currentStreak) currentStreak = stats.currentStreak;
		}
		return { tasks: tasks.length, checkins, currentStreak };
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
		readCachedTrackers,
		writeCachedTrackers,
		periodOrdinal,
		taskStats,
		trackerTaskStats,
	};
});
