// App-shell cache for read-only offline use. Bump CACHE to force a shell refresh.
const CACHE = "long-time-shell-v7";
const SHELL = ["/", "/app.css", "/logic.js", "/app.js", "/vendor/alpine-3.14.9.min.js"];

self.addEventListener("install", (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.addAll(SHELL))
			.then(() => self.skipWaiting()),
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
			if (cached) return cached;
			try {
				return await fetch(request);
			} catch (_error) {
				if (request.mode === "navigate") return cache.match("/");
				return Response.error();
			}
		}),
	);
});
