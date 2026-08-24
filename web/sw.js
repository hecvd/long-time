// App-shell cache for read-only offline use. Bump CACHE to force a shell refresh.
const CACHE = "long-time-shell-v1";
const SHELL = [
	"/",
	"/app.css",
	"/logic.js",
	"/app.js",
	"/vendor/alpine-3.14.9.min.js",
];

self.addEventListener("install", (event) => {
	event.waitUntil(
		caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()),
	);
});

self.addEventListener("activate", (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
			.then(() => self.clients.claim()),
	);
});

self.addEventListener("fetch", (event) => {
	const request = event.request;
	if (request.method !== "GET") return;

	const url = new URL(request.url);
	// The API is never cached here; the app keeps its own data cache in localStorage.
	if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

	event.respondWith(
		caches.open(CACHE).then(async (cache) => {
			const cached = await cache.match(request);
			const network = fetch(request)
				.then((response) => {
					if (response && response.ok) cache.put(request, response.clone());
					return response;
				})
				.catch(() => null);
			// Stale-while-revalidate: serve cache immediately, refresh in the background.
			const response = cached || (await network);
			if (response) return response;
			// Offline navigation with no exact match: fall back to the cached shell.
			if (request.mode === "navigate") return cache.match("/");
			return Response.error();
		}),
	);
});
