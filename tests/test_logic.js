const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const logic = require("../web/logic.js");

test("elapsedParts reports future and elapsed units", () => {
	assert.deepEqual(
		logic.elapsedParts(
			"2024-01-01T00:00:00Z",
			new Date("2024-01-15T12:00:00Z"),
		),
		{
			future: false,
			hours: 348,
			days: 14,
			weeks: 2.1,
			years: 0.04,
		},
	);
	assert.equal(
		logic.elapsedParts("2025-01-01T00:00:00Z", new Date("2024-01-01T00:00:00Z"))
			.future,
		true,
	);
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
	assert.equal(
		logic.resolvedMilestoneTarget(tracker, annual).toISOString(),
		"2025-02-28T10:15:00.000Z",
	);
	assert.equal(
		logic.milestoneState(tracker, annual, new Date("2025-01-01T00:00:00Z"))
			.future,
		true,
	);
});

test("calendar month milestones clamp to the destination month end", () => {
	const tracker = { started_at: "2024-01-31T10:15:00Z" };
	const monthly = {
		target_mode: "duration",
		target_value: 1,
		target_unit: "months",
	};
	assert.equal(
		logic.resolvedMilestoneTarget(tracker, monthly).toISOString(),
		"2024-02-29T10:15:00.000Z",
	);
});

test("calendarDurationParts decomposes past and future durations", () => {
	assert.deepEqual(
		logic.calendarDurationParts(
			"2022-10-31T10:15:00Z",
			new Date("2025-02-03T15:45:00Z"),
		),
		{ future: false, years: 2, months: 3, days: 3, hours: 5 },
	);
	assert.deepEqual(
		logic.calendarDurationParts(
			"2025-02-03T15:45:00Z",
			new Date("2022-10-31T10:15:00Z"),
		),
		{ future: true, years: 2, months: 3, days: 3, hours: 5 },
	);
});

test("formatClosestDuration chooses the nearest useful unit", () => {
	assert.equal(
		logic.formatClosestDuration({ years: 2, months: 3, days: 2, hours: 1 }),
		"2 years",
	);
	assert.equal(
		logic.formatClosestDuration({ years: 0, months: 3, days: 2, hours: 1 }),
		"3 months",
	);
	assert.equal(
		logic.formatClosestDuration({ years: 0, months: 0, days: 18, hours: 1 }),
		"2 weeks",
	);
	assert.equal(
		logic.formatClosestDuration({ years: 0, months: 0, days: 2, hours: 1 }),
		"2 days",
	);
	assert.equal(
		logic.formatClosestDuration({ years: 0, months: 0, days: 0, hours: 1 }),
		"1 hour",
	);
});

test("safePreference tolerates unavailable or invalid storage", () => {
	const storage = {
		getItem: () => {
			throw new Error("blocked");
		},
	};
	assert.equal(
		logic.safePreference(storage, "theme", "system", ["system", "dark"]),
		"system",
	);
	assert.equal(
		logic.safePreference({ getItem: () => "other" }, "theme", "system", [
			"system",
			"dark",
		]),
		"system",
	);
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
	assert.equal(
		logic.entryTimingLabel(
			tracker,
			milestone,
			new Date("2024-01-01T00:00:00Z"),
		),
		"2 weeks remaining",
	);
	assert.equal(
		logic.entryTimingLabel(
			tracker,
			milestone,
			new Date("2024-01-28T00:00:00Z"),
		),
		"13 days ago",
	);
});

test("tracker page uses adaptive time and omits the introductory copy", () => {
	const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
	assert.match(html, /formattedClosestDuration\(tracker\)/);
	assert.match(html, /value="months">Calendar months/);
	assert.doesNotMatch(html, /A quiet living ledger|Time, made visible|trackerCountLabel|class="intro"/);
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
