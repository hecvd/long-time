class ApiRequestError extends Error {
	constructor(status, code, message, fieldErrors = {}) {
		super(message);
		this.status = status;
		this.code = code;
		this.fieldErrors = fieldErrors;
	}
}

async function api(path, options = {}) {
	const request = { ...options, headers: { ...(options.headers || {}) } };
	if (request.body && typeof request.body !== "string") {
		request.headers["Content-Type"] = "application/json";
		request.body = JSON.stringify(request.body);
	}
	let response;
	try {
		response = await fetch(path, request);
	} catch (_error) {
		throw new ApiRequestError(
			0,
			"network_error",
			"Long Time could not reach the server.",
		);
	}
	if (response.status === 204) return null;
	let payload;
	try {
		payload = await response.json();
	} catch (_error) {
		throw new ApiRequestError(
			response.status,
			"invalid_response",
			"The server returned an unreadable response.",
		);
	}
	if (!response.ok) {
		const error = payload.error || {};
		throw new ApiRequestError(
			response.status,
			error.code,
			error.message || "The request failed.",
			error.field_errors,
		);
	}
	return payload;
}

function emptyTrackerForm() {
	return { id: null, title: "", description: "", started_at: "" };
}

function emptyEntryForm() {
	return {
		id: null,
		kind: "note",
		title: "",
		body: "",
		occurred_at: "",
		target_mode: "date",
		target_at: "",
		target_value: 1,
		target_unit: "years",
	};
}

function localInputValue(value) {
	if (!value) return "";
	const date = new Date(value);
	const offset = date.getTimezoneOffset() * 60_000;
	return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function apiTimestamp(value) {
	return value ? new Date(value).toISOString() : null;
}

window.longTimeApp = function longTimeApp() {
	return {
		trackers: [],
		loading: true,
		stale: false,
		globalError: "",
		statusMessage: "",
		filter: "",
		sortMode: "recent",
		themeMode: "system",
		expandedId: null,
		trackerForm: emptyTrackerForm(),
		trackerErrors: {},
		trackerFormError: "",
		savingTracker: false,
		entryForm: emptyEntryForm(),
		entryErrors: {},
		entryFormError: "",
		savingEntry: false,
		quickNotes: {},
		quickNoteErrors: {},
		savingQuickNoteId: null,
		importMode: "append",
		importError: "",
		importing: false,
		activeTrackerId: null,
		confirmation: null,
		deleting: false,
		now: new Date(),
		lastLoadedAt: 0,
		clockTimer: null,
		returnFocus: null,

		get visibleTrackers() {
			return LongTimeLogic.sortTrackers(
				LongTimeLogic.filterTrackers(this.trackers, this.filter),
				this.sortMode,
			);
		},

		get themeLabel() {
			return {
				system: "System theme",
				light: "Light theme",
				dark: "Dark theme",
			}[this.themeMode];
		},

		async init() {
			this.restorePreferences();
			this.applyTheme();
			this.$watch("filter", (value) =>
				this.storePreference("long-time:filter", value),
			);
			this.$watch("sortMode", (value) =>
				this.storePreference("long-time:sort", value),
			);
			this.$watch("expandedId", (value) =>
				this.storePreference("long-time:expanded", value ?? ""),
			);
			this.onFocus = () => {
				if (LongTimeLogic.shouldRefreshOnFocus(this.lastLoadedAt))
					this.loadTrackers({ preserve: true });
			};
			this.onVisibility = () => {
				if (document.hidden) this.stopClock();
				else {
					this.now = new Date();
					this.startClock();
				}
			};
			window.addEventListener("focus", this.onFocus);
			document.addEventListener("visibilitychange", this.onVisibility);
			this.startClock();
			await this.loadTrackers();
		},

		destroy() {
			window.removeEventListener("focus", this.onFocus);
			document.removeEventListener("visibilitychange", this.onVisibility);
			this.stopClock();
		},

		startClock() {
			if (!this.clockTimer && !document.hidden) {
				this.clockTimer = window.setInterval(() => {
					this.now = new Date();
				}, 60_000);
			}
		},

		stopClock() {
			window.clearInterval(this.clockTimer);
			this.clockTimer = null;
		},

		restorePreferences() {
			try {
				this.filter = localStorage.getItem("long-time:filter") || "";
			} catch (_error) {
				this.filter = "";
			}
			this.sortMode = LongTimeLogic.safePreference(
				localStorage,
				"long-time:sort",
				"recent",
				["recent", "start-asc", "start-desc", "name-asc", "name-desc"],
			);
			this.themeMode = LongTimeLogic.safePreference(
				localStorage,
				"long-time:theme",
				"system",
				["system", "light", "dark"],
			);
			try {
				const value = localStorage.getItem("long-time:expanded");
				this.expandedId = /^\d+$/.test(value || "") ? Number(value) : null;
			} catch (_error) {
				this.expandedId = null;
			}
		},

		storePreference(key, value) {
			try {
				localStorage.setItem(key, String(value));
			} catch (_error) {
				return;
			}
		},

		applyTheme() {
			if (this.themeMode === "system")
				delete document.documentElement.dataset.theme;
			else document.documentElement.dataset.theme = this.themeMode;
		},

		cycleTheme() {
			const modes = ["system", "light", "dark"];
			this.themeMode =
				modes[(modes.indexOf(this.themeMode) + 1) % modes.length];
			this.applyTheme();
			this.storePreference("long-time:theme", this.themeMode);
			this.announce(this.themeLabel);
		},

		async loadTrackers({ preserve = false } = {}) {
			if (!preserve) this.loading = true;
			this.globalError = "";
			try {
				this.trackers = await api("/api/trackers");
				this.stale = false;
				this.lastLoadedAt = Date.now();
				if (
					this.expandedId &&
					!this.trackers.some((tracker) => tracker.id === this.expandedId)
				)
					this.expandedId = null;
			} catch (error) {
				if (preserve && this.trackers.length) this.stale = true;
				else this.globalError = error.message;
			} finally {
				this.loading = false;
			}
		},

		rememberFocus() {
			this.returnFocus = document.activeElement;
		},
		restoreFocus() {
			window.setTimeout(() => this.returnFocus?.focus(), 0);
		},
		announce(message) {
			this.statusMessage = "";
			this.$nextTick(() => {
				this.statusMessage = message;
			});
		},

		exportData() {
			window.location.href = "/api/export";
		},

		openImport() {
			this.rememberFocus();
			this.importMode = "append";
			this.importError = "";
			if (this.$refs.importFile) this.$refs.importFile.value = "";
			this.$refs.importDialog.showModal();
		},

		closeImport() {
			if (this.importing) return;
			this.$refs.importDialog.close();
			this.restoreFocus();
		},

		async runImport() {
			this.importError = "";
			const file = this.$refs.importFile.files[0];
			if (!file) {
				this.importError = "Choose a file to import.";
				return;
			}
			let data;
			try {
				data = JSON.parse(await file.text());
			} catch (_error) {
				this.importError = "That file is not valid JSON.";
				return;
			}
			if (!data || !Array.isArray(data.trackers)) {
				this.importError = "That file does not look like a Long Time export.";
				return;
			}
			this.importing = true;
			try {
				const result = await api("/api/import", {
					method: "POST",
					body: { mode: this.importMode, trackers: data.trackers },
				});
				this.$refs.importDialog.close();
				this.$refs.importFile.value = "";
				await this.loadTrackers();
				this.announce(
					`Imported ${result.trackers} tracker${result.trackers === 1 ? "" : "s"}.`,
				);
				this.restoreFocus();
			} catch (error) {
				this.importError = error.message;
			} finally {
				this.importing = false;
			}
		},

		openNewTracker() {
			this.rememberFocus();
			this.trackerForm = {
				...emptyTrackerForm(),
				started_at: localInputValue(new Date()),
			};
			this.trackerErrors = {};
			this.trackerFormError = "";
			this.$refs.trackerDialog.showModal();
		},

		openEditTracker(tracker) {
			this.rememberFocus();
			this.trackerForm = {
				id: tracker.id,
				title: tracker.title,
				description: tracker.description,
				started_at: localInputValue(tracker.started_at),
			};
			this.trackerErrors = {};
			this.trackerFormError = "";
			this.$refs.trackerDialog.showModal();
		},

		closeTrackerDialog() {
			if (this.savingTracker) return;
			this.$refs.trackerDialog.close();
			this.restoreFocus();
		},

		async saveTracker() {
			this.savingTracker = true;
			this.trackerErrors = {};
			this.trackerFormError = "";
			const editing = Boolean(this.trackerForm.id);
			try {
				await api(
					editing ? `/api/trackers/${this.trackerForm.id}` : "/api/trackers",
					{
						method: editing ? "PUT" : "POST",
						body: {
							title: this.trackerForm.title,
							description: this.trackerForm.description,
							started_at: apiTimestamp(this.trackerForm.started_at),
						},
					},
				);
				this.$refs.trackerDialog.close();
				await this.loadTrackers({ preserve: true });
				this.announce(editing ? "Tracker updated." : "Tracker created.");
				this.restoreFocus();
			} catch (error) {
				this.trackerErrors = error.fieldErrors || {};
				this.trackerFormError = error.message;
			} finally {
				this.savingTracker = false;
			}
		},

		toggleTracker(id) {
			this.expandedId = this.expandedId === id ? null : id;
		},

		requestTrackerDelete(tracker) {
			this.rememberFocus();
			this.confirmation = {
				kind: "tracker",
				id: tracker.id,
				name: tracker.title,
			};
			this.$refs.confirmDialog.showModal();
		},

		async addQuickNote(tracker) {
			const title = (this.quickNotes[tracker.id] || "").trim();
			this.quickNoteErrors[tracker.id] = "";
			if (!title || this.savingQuickNoteId) return;
			this.savingQuickNoteId = tracker.id;
			try {
				await api(`/api/trackers/${tracker.id}/entries`, {
					method: "POST",
					body: {
						kind: "note",
						title,
						body: "",
						occurred_at: new Date().toISOString(),
					},
				});
				this.quickNotes[tracker.id] = "";
				await this.loadTrackers({ preserve: true });
				this.announce("Note added.");
			} catch (error) {
				this.quickNoteErrors[tracker.id] = error.message;
			} finally {
				this.savingQuickNoteId = null;
			}
		},

		openNewNote(tracker) {
			this.openNewEntry(tracker, "note");
		},
		openNewMilestone(tracker) {
			this.openNewEntry(tracker, "milestone");
		},

		openNewEntry(tracker, kind) {
			this.rememberFocus();
			this.activeTrackerId = tracker.id;
			this.entryForm = {
				...emptyEntryForm(),
				kind,
				occurred_at: localInputValue(new Date()),
				target_at: localInputValue(new Date()),
			};
			this.entryErrors = {};
			this.entryFormError = "";
			this.$refs.entryDialog.showModal();
		},

		openEditEntry(tracker, entry) {
			this.rememberFocus();
			this.activeTrackerId = tracker.id;
			this.entryForm = {
				...emptyEntryForm(),
				...entry,
				occurred_at: localInputValue(entry.occurred_at),
				target_at: localInputValue(entry.target_at),
			};
			this.entryErrors = {};
			this.entryFormError = "";
			this.$refs.entryDialog.showModal();
		},

		closeEntryDialog() {
			if (this.savingEntry) return;
			this.$refs.entryDialog.close();
			this.restoreFocus();
		},

		async saveEntry() {
			this.savingEntry = true;
			this.entryErrors = {};
			this.entryFormError = "";
			const editing = Boolean(this.entryForm.id);
			const payload = {
				kind: this.entryForm.kind,
				title: this.entryForm.title,
				body: this.entryForm.body,
			};
			if (payload.kind === "note")
				payload.occurred_at = apiTimestamp(this.entryForm.occurred_at);
			else {
				payload.target_mode = this.entryForm.target_mode;
				if (payload.target_mode === "date")
					payload.target_at = apiTimestamp(this.entryForm.target_at);
				else {
					payload.target_value = Number(this.entryForm.target_value);
					payload.target_unit = this.entryForm.target_unit;
				}
			}
			try {
				await api(
					editing
						? `/api/entries/${this.entryForm.id}`
						: `/api/trackers/${this.activeTrackerId}/entries`,
					{
						method: editing ? "PUT" : "POST",
						body: payload,
					},
				);
				this.$refs.entryDialog.close();
				await this.loadTrackers({ preserve: true });
				this.announce(editing ? "Entry updated." : "Entry added.");
				this.restoreFocus();
			} catch (error) {
				this.entryErrors = error.fieldErrors || {};
				this.entryFormError = error.message;
			} finally {
				this.savingEntry = false;
			}
		},

		requestEntryDelete(entry) {
			this.rememberFocus();
			this.confirmation = { kind: "entry", id: entry.id, name: entry.title };
			this.$refs.confirmDialog.showModal();
		},

		closeConfirmation() {
			if (this.deleting) return;
			this.$refs.confirmDialog.close();
			this.restoreFocus();
		},

		async confirmDelete() {
			this.deleting = true;
			try {
				const endpoint =
					this.confirmation.kind === "tracker"
						? `/api/trackers/${this.confirmation.id}`
						: `/api/entries/${this.confirmation.id}`;
				await api(endpoint, { method: "DELETE" });
				const label =
					this.confirmation.kind === "tracker" ? "Tracker" : "Entry";
				this.$refs.confirmDialog.close();
				await this.loadTrackers({ preserve: true });
				this.announce(`${label} deleted.`);
				this.restoreFocus();
			} catch (error) {
				this.globalError = error.message;
			} finally {
				this.deleting = false;
			}
		},

		elapsed(tracker) {
			return LongTimeLogic.elapsedParts(tracker.started_at, this.now);
		},
		calendarDuration(tracker) {
			return LongTimeLogic.calendarDurationParts(tracker.started_at, this.now);
		},
		formattedClosestDuration(tracker) {
			return LongTimeLogic.formatClosestDuration(
				this.calendarDuration(tracker),
			);
		},
		orderedEntries(tracker) {
			return LongTimeLogic.orderedEntries(tracker);
		},
		entryTimingLabel(tracker, entry) {
			return LongTimeLogic.entryTimingLabel(tracker, entry, this.now);
		},
		entryIsFuture(tracker, entry) {
			const timestamp =
				entry.kind === "note"
					? new Date(entry.occurred_at)
					: LongTimeLogic.resolvedMilestoneTarget(tracker, entry);
			return timestamp > this.now;
		},
		formatTimestamp(value) {
			return new Intl.DateTimeFormat(undefined, {
				dateStyle: "medium",
				timeStyle: "short",
			}).format(new Date(value));
		},
	};
};
