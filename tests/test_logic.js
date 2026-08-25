const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const logic = require("../web/logic.js");

test("elapsedParts reports future and elapsed units", () => {
	assert.deepEqual(logic.elapsedParts("2024-01-01T00:00:00Z", new Date("2024-01-15T12:00:00Z")), {
		future: false,
		hours: 348,
		days: 14,
		weeks: 2.1,
		years: 0.04,
	});
	assert.equal(logic.elapsedParts("2025-01-01T00:00:00Z", new Date("2024-01-01T00:00:00Z")).future, true);
});

test("filterTrackers searches tracker and entry text", () => {
	const trackers = [
		{
			title: "Piano",
			description: "",
			entries: [{ title: "Daily practice", body: "" }],
		},
	];
	assert.equal(logic.filterTrackers(trackers, "practice").length, 1);
	assert.equal(logic.filterTrackers(trackers, "running").length, 0);
});

test("sortTrackers returns a copy in requested order", () => {
	const trackers = [
		{
			title: "Zulu",
			started_at: "2024-01-02T00:00:00Z",
			updated_at: "2024-01-03T00:00:00Z",
		},
		{
			title: "alpha",
			started_at: "2024-01-01T00:00:00Z",
			updated_at: "2024-01-04T00:00:00Z",
		},
	];
	const sorted = logic.sortTrackers(trackers, "name-asc");
	assert.deepEqual(
		sorted.map((item) => item.title),
		["alpha", "Zulu"],
	);
	assert.notEqual(sorted, trackers);
});

test("milestone dates resolve calendar years and duration units", () => {
	const tracker = { started_at: "2024-02-29T10:15:00Z" };
	const annual = {
		target_mode: "duration",
		target_value: 1,
		target_unit: "years",
	};
	assert.equal(logic.resolvedMilestoneTarget(tracker, annual).toISOString(), "2025-02-28T10:15:00.000Z");
	assert.equal(logic.milestoneState(tracker, annual, new Date("2025-01-01T00:00:00Z")).future, true);
});

test("calendar month milestones clamp to the destination month end", () => {
	const tracker = { started_at: "2024-01-31T10:15:00Z" };
	const monthly = {
		target_mode: "duration",
		target_value: 1,
		target_unit: "months",
	};
	assert.equal(logic.resolvedMilestoneTarget(tracker, monthly).toISOString(), "2024-02-29T10:15:00.000Z");
});

test("resolvedMilestoneTarget does not use duration math for task-only milestones", () => {
	const tracker = { started_at: "2024-01-01T10:00:00Z" };
	const target = logic.resolvedMilestoneTarget(tracker, {
		target_mode: "none",
	});
	assert.equal(target.toISOString(), "2024-01-01T10:00:00.000Z");
});

test("calendarDurationParts decomposes past and future durations", () => {
	assert.deepEqual(logic.calendarDurationParts("2022-10-31T10:15:00Z", new Date("2025-02-03T15:45:00Z")), {
		future: false,
		years: 2,
		months: 3,
		days: 3,
		hours: 5,
	});
	assert.deepEqual(logic.calendarDurationParts("2025-02-03T15:45:00Z", new Date("2022-10-31T10:15:00Z")), {
		future: true,
		years: 2,
		months: 3,
		days: 3,
		hours: 5,
	});
});

test("formatClosestDuration chooses the nearest useful unit", () => {
	assert.equal(logic.formatClosestDuration({ years: 2, months: 3, days: 2, hours: 1 }), "2 years");
	assert.equal(logic.formatClosestDuration({ years: 0, months: 3, days: 2, hours: 1 }), "3 months");
	assert.equal(logic.formatClosestDuration({ years: 0, months: 0, days: 18, hours: 1 }), "2 weeks");
	assert.equal(logic.formatClosestDuration({ years: 0, months: 0, days: 2, hours: 1 }), "2 days");
	assert.equal(logic.formatClosestDuration({ years: 0, months: 0, days: 0, hours: 1 }), "1 hour");
});

test("safePreference tolerates unavailable or invalid storage", () => {
	const storage = {
		getItem: () => {
			throw new Error("blocked");
		},
	};
	assert.equal(logic.safePreference(storage, "theme", "system", ["system", "dark"]), "system");
	assert.equal(logic.safePreference({ getItem: () => "other" }, "theme", "system", ["system", "dark"]), "system");
});

test("orderedEntries uses resolved timestamps newest first", () => {
	const tracker = {
		started_at: "2024-01-01T00:00:00Z",
		entries: [
			{ id: 1, kind: "note", occurred_at: "2024-01-02T00:00:00Z" },
			{
				id: 2,
				kind: "milestone",
				target_mode: "duration",
				target_value: 2,
				target_unit: "weeks",
			},
		],
	};
	assert.deepEqual(
		logic.orderedEntries(tracker).map((item) => item.id),
		[2, 1],
	);
});

test("entryTimingLabel describes notes and milestones", () => {
	const tracker = { started_at: "2024-01-01T00:00:00Z" };
	assert.equal(
		logic.entryTimingLabel(tracker, {
			kind: "note",
			occurred_at: "2024-01-02T00:00:00Z",
		}),
		"24 hours after start",
	);
	const milestone = {
		kind: "milestone",
		target_mode: "duration",
		target_value: 2,
		target_unit: "weeks",
	};
	assert.equal(logic.entryTimingLabel(tracker, milestone, new Date("2024-01-01T00:00:00Z")), "2 weeks remaining");
	assert.equal(logic.entryTimingLabel(tracker, milestone, new Date("2024-01-28T00:00:00Z")), "13 days ago");
});

test("tracker page uses adaptive time and omits the introductory copy", () => {
	const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
	assert.match(html, /formattedClosestDuration\(tracker\)/);
	assert.match(html, /value="months">Calendar months/);
	assert.doesNotMatch(html, /A quiet living ledger|Time, made visible|trackerCountLabel|class="intro"/);
});

function fakeStorage(initial = {}) {
	const map = new Map(Object.entries(initial));
	return {
		getItem: (key) => (map.has(key) ? map.get(key) : null),
		setItem: (key, value) => map.set(key, String(value)),
	};
}

test("cached trackers round-trip and degrade to empty", () => {
	const storage = fakeStorage();
	assert.deepEqual(logic.readCachedTrackers(storage), []);
	logic.writeCachedTrackers(storage, [{ id: 1, title: "Piano" }]);
	assert.deepEqual(logic.readCachedTrackers(storage), [{ id: 1, title: "Piano" }]);
	assert.deepEqual(logic.readCachedTrackers(fakeStorage({ "long-time:data": "{not json" })), []);
	assert.deepEqual(logic.readCachedTrackers(fakeStorage({ "long-time:data": '"scalar"' })), []);
});

test("offline shell and data cache are wired", () => {
	const sw = fs.readFileSync(path.join(__dirname, "..", "web", "sw.js"), "utf8");
	assert.match(sw, /const CACHE = "long-time-shell-v3"/);
	assert.match(sw, /"\/app\.js"/);
	assert.match(sw, /startsWith\("\/api\/"\)/);

	const app = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
	assert.match(app, /navigator\.serviceWorker\.register\("\/sw\.js"\)/);
	assert.match(app, /readCachedTrackers\(localStorage\)/);
	assert.match(app, /writeCachedTrackers\(localStorage, this\.trackers\)/);
});

test("toolbar wires import and export", () => {
	const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
	assert.match(html, /@click="exportData\(\)"/);
	assert.match(html, /@click="openImport\(\)"/);
	assert.match(html, /x-ref="importDialog"/);
	assert.match(html, /x-ref="importFile"/);

	const app = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
	assert.match(app, /async runImport\(\)/);
	assert.match(app, /"\/api\/import"/);
	assert.match(app, /window\.location\.href = "\/api\/export"/);
});

test("rail marks cleared milestones distinctly", () => {
	const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
	assert.match(html, /'cleared': entry\.kind === 'milestone' && !entryIsFuture\(tracker, entry\)/);
	const css = fs.readFileSync(path.join(__dirname, "..", "web", "app.css"), "utf8");
	assert.match(css, /--cleared:/);
	assert.match(css, /\.rail li\.cleared \.rail-marker/);
});

test("resolvedMilestoneTarget treats four_weeks as 28 days", () => {
	const tracker = { started_at: "2024-01-01T00:00:00Z" };
	const target = logic.resolvedMilestoneTarget(tracker, {
		target_mode: "duration",
		target_value: 1.5,
		target_unit: "four_weeks",
	});
	assert.equal(target.toISOString(), "2024-02-12T00:00:00.000Z");
});

test("duration form offers a four-week month and allows whole calendar months", () => {
	const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
	assert.match(html, /<option value="four_weeks">Months \(4 weeks\)<\/option>/);
	assert.match(html, /:min="\['months', 'years'\]\.includes\(entryForm\.target_unit\) \? 1 : 0\.01"/);
});

test("tracker page exposes an inline quick-note form", () => {
	const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
	assert.match(html, /class="quick-note"/);
	assert.match(html, /@submit\.prevent="addQuickNote\(tracker\)"/);
	assert.match(html, /x-model="quickNotes\[tracker\.id\]"/);

	const app = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
	assert.match(app, /async addQuickNote\(tracker\)/);
	assert.match(app, /occurred_at: new Date\(\)\.toISOString\(\)/);
});

test("shouldRefreshOnFocus waits five seconds", () => {
	assert.equal(logic.shouldRefreshOnFocus(1_000, 5_999), false);
	assert.equal(logic.shouldRefreshOnFocus(1_000, 6_000), true);
});

test("periodOrdinal numbers consecutive days and weeks by one", () => {
	const day = (y, m, d) => new Date(y, m, d, 12, 0, 0);
	assert.equal(logic.periodOrdinal(day(2024, 0, 2), "day") - logic.periodOrdinal(day(2024, 0, 1), "day"), 1);
	// Same ISO week (Mon 2024-01-01 .. Sun 2024-01-07) → same ordinal.
	assert.equal(logic.periodOrdinal(day(2024, 0, 1), "week"), logic.periodOrdinal(day(2024, 0, 7), "week"));
	// Next week → +1.
	assert.equal(logic.periodOrdinal(day(2024, 0, 8), "week") - logic.periodOrdinal(day(2024, 0, 1), "week"), 1);
});

test("taskStats derives counts, latest rate, and streaks", () => {
	const at = (y, m, d) => Math.floor(new Date(y, m, d, 12, 0, 0).getTime() / 1000);
	const task = {
		per_period: 1,
		period_unit: "day",
		checkins: [
			{ occurred_at: at(2024, 0, 1), changed: true, checked_count: 1, total_count: 2 },
			{ occurred_at: at(2024, 0, 2), changed: false, checked_count: 1, total_count: 2 },
			{ occurred_at: at(2024, 0, 3), changed: true, checked_count: 2, total_count: 2 },
		],
	};
	const stats = logic.taskStats(task, new Date(2024, 0, 3, 15, 0, 0));
	assert.equal(stats.total, 3);
	assert.deepEqual(stats.latestRate, { checked: 2, total: 2 });
	assert.equal(stats.currentStreak, 3);
	assert.equal(stats.longestStreak, 3);
});

test("taskStats resets the current streak after a missed period", () => {
	const at = (y, m, d) => Math.floor(new Date(y, m, d, 12, 0, 0).getTime() / 1000);
	const task = {
		per_period: 1,
		period_unit: "day",
		checkins: [
			{ occurred_at: at(2024, 0, 1), changed: true, checked_count: 1, total_count: 1 },
			{ occurred_at: at(2024, 0, 3), changed: true, checked_count: 1, total_count: 1 },
		],
	};
	const stats = logic.taskStats(task, new Date(2024, 0, 3, 15, 0, 0));
	assert.equal(stats.currentStreak, 1);
	assert.equal(stats.longestStreak, 1);
});

test("taskStats honors per_period greater than one", () => {
	const at = (y, m, d, h) => Math.floor(new Date(y, m, d, h, 0, 0).getTime() / 1000);
	const task = {
		per_period: 2,
		period_unit: "day",
		checkins: [
			{ occurred_at: at(2024, 0, 1, 9), changed: true, checked_count: 1, total_count: 1 },
			{ occurred_at: at(2024, 0, 1, 18), changed: false, checked_count: 1, total_count: 1 },
		],
	};
	const stats = logic.taskStats(task, new Date(2024, 0, 1, 20, 0, 0));
	assert.equal(stats.currentStreak, 1);
});

test("taskStats buckets week cadence by local ISO week", () => {
	const at = (y, m, d) => Math.floor(new Date(y, m, d, 12, 0, 0).getTime() / 1000);
	const task = {
		per_period: 1,
		period_unit: "week",
		checkins: [
			{ occurred_at: at(2024, 0, 2), changed: true, checked_count: 1, total_count: 1 },
			{ occurred_at: at(2024, 0, 9), changed: true, checked_count: 1, total_count: 1 },
		],
	};
	const stats = logic.taskStats(task, new Date(2024, 0, 10, 12, 0, 0));
	assert.equal(stats.currentStreak, 2);
});

test("taskStats current streak is zero when per_period is unmet today", () => {
	const at = (y, m, d) => Math.floor(new Date(y, m, d, 12, 0, 0).getTime() / 1000);
	const task = {
		per_period: 2,
		period_unit: "day",
		checkins: [{ occurred_at: at(2024, 0, 1), changed: true, checked_count: 1, total_count: 1 }],
	};
	const stats = logic.taskStats(task, new Date(2024, 0, 1, 15, 0, 0));
	assert.equal(stats.currentStreak, 0);
});

test("taskStats current streak continues when today is not yet satisfied", () => {
	const at = (y, m, d) => Math.floor(new Date(y, m, d, 12, 0, 0).getTime() / 1000);
	const task = {
		per_period: 1,
		period_unit: "day",
		checkins: [
			{ occurred_at: at(2024, 0, 1), changed: true, checked_count: 1, total_count: 1 },
			{ occurred_at: at(2024, 0, 2), changed: true, checked_count: 1, total_count: 1 },
		],
	};
	const stats = logic.taskStats(task, new Date(2024, 0, 3, 9, 0, 0));
	assert.equal(stats.currentStreak, 2);
});

test("taskStats latestRate follows the newest occurred_at", () => {
	const at = (y, m, d) => Math.floor(new Date(y, m, d, 12, 0, 0).getTime() / 1000);
	const task = {
		per_period: 1,
		period_unit: "day",
		checkins: [
			{ occurred_at: at(2024, 0, 2), changed: true, checked_count: 2, total_count: 2 },
			{ occurred_at: at(2024, 0, 1), changed: true, checked_count: 1, total_count: 1 },
		],
	};
	assert.deepEqual(logic.taskStats(task, new Date(2024, 0, 2, 15, 0, 0)).latestRate, {
		checked: 2,
		total: 2,
	});
});

test("trackerTaskStats rolls up checklists on a tracker", () => {
	const at = (y, m, d) => Math.floor(new Date(y, m, d, 12, 0, 0).getTime() / 1000);
	const now = new Date(2024, 0, 3, 15, 0, 0);
	const empty = logic.trackerTaskStats({ entries: [{ kind: "note" }] }, now);
	assert.deepEqual(empty, { tasks: 0, checkins: 0, currentStreak: 0 });

	const stats = logic.trackerTaskStats(
		{
			entries: [
				{ kind: "note" },
				{
					kind: "milestone",
					task: {
						per_period: 1,
						period_unit: "day",
						checkins: [
							{ occurred_at: at(2024, 0, 1), changed: true },
							{ occurred_at: at(2024, 0, 2), changed: true },
							{ occurred_at: at(2024, 0, 3), changed: true },
						],
					},
				},
				{
					kind: "milestone",
					task: {
						per_period: 1,
						period_unit: "day",
						checkins: [{ occurred_at: at(2024, 0, 3), changed: true }],
					},
				},
			],
		},
		now,
	);
	assert.equal(stats.tasks, 2);
	assert.equal(stats.checkins, 4);
	assert.equal(stats.currentStreak, 3);
});

test("check-in card and checklist editor are wired", () => {
	const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
	assert.match(html, /class="check-in-card"/);
	assert.match(html, /@change="toggleTaskItem\(entry, item\)"/);
	assert.match(html, /@click="checkIn\(entry\)"/);
	assert.match(html, /x-text="taskStatsLabel\(entry\)"/);
	assert.match(html, /@click="addTaskItem\(\)"/);
	assert.match(html, /x-model="entryForm\.period_unit"/);
	assert.match(html, /x-model="entryForm\.has_deadline"/);
	assert.match(html, /:key="item\.key"/);
	assert.match(html, /<h3>Tasks<\/h3>/);
	assert.match(html, /<h3>Timeline<\/h3>/);
	assert.match(html, /<h3>Tasks<\/h3>[\s\S]*<h3>Timeline<\/h3>/);
	assert.match(html, /empty-section" x-show="!taskEntries\(tracker\)\.length"/);
	assert.match(html, /empty-section" x-show="!railEntries\(tracker\)\.length"/);
	assert.match(html, /entryErrors\['task\.per_period'\]/);
	assert.match(html, /class="measurements task-measurements"/);
	assert.match(html, /trackerTaskStats\(tracker\)/);

	const app = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
	assert.match(app, /trackerTaskStats\(tracker\)/);
	assert.match(app, /async checkIn\(entry\)/);
	assert.match(app, /async toggleTaskItem\(entry, item\)/);
	assert.match(app, /taskStatsLabel\(entry\)/);
	assert.match(app, /railEntries\(tracker\)/);
	assert.match(app, /taskEntries\(tracker\)/);
	assert.match(app, /payload\.task = null/);
});
