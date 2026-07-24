import {
	createStartHandler,
	defaultStreamHandler,
} from "@tanstack/react-start/server";
import { apiHandler } from "#/api/live";
import { mjpegBase } from "#/api/services/driver-manager";
import { hubAuthorized } from "#/hub/auth";
import { handleHubRequest } from "#/hub/routes";
import { startRigLink } from "#/rig/link";

const startFetch = createStartHandler(defaultStreamHandler);

// One build, three roles, resolved from env at boot:
//   hub     — the deployed cloud app: lobby + drive UI, relay. No driver.
//   console — the local lab tool (default); setting HUB_URL also registers it.
//   agent   — headless rig: local API + rig link only, serves no UI.
type Role = "hub" | "agent" | "console";
const ROLE: Role =
	process.env.LAB_MODE === "hub"
		? "hub"
		: process.env.LAB_MODE === "agent"
			? "agent"
			: "console";
const HUB_URL = process.env.HUB_URL;
const RIG_NAME = process.env.RIG_NAME ?? "local-rig";

const boot = globalThis as unknown as { __labRigLinkStarted?: boolean };
if (HUB_URL && ROLE !== "hub" && !boot.__labRigLinkStarted) {
	boot.__labRigLinkStarted = true;
	startRigLink({
		hubUrl: HUB_URL,
		rigName: RIG_NAME,
		autoConnect: process.env.LAB_AUTOCONNECT,
		token: process.env.HUB_TOKEN,
	});
}
if (ROLE === "agent" && !HUB_URL)
	console.error(
		"[agent] LAB_MODE=agent without HUB_URL — this rig serves no UI and dials no hub; set HUB_URL",
	);

export default {
	// Bun honors PORT implicitly; explicit so the contract is visible (Railway).
	port: Number(process.env.PORT ?? 3000),
	hostname: "0.0.0.0",
	async fetch(request: Request): Promise<Response> {
		const url = new URL(request.url);

		// Which half of the app this process is. The roles ship as one build and
		// differ only by env, so the client has to ask at runtime. An agent is
		// still a rig to everyone who talks to it.
		if (url.pathname === "/api/mode") {
			return new Response(
				JSON.stringify({
					mode: ROLE === "hub" ? "hub" : "rig",
					rigName: RIG_NAME,
				}),
				{ headers: { "content-type": "application/json" } },
			);
		}

		// Hub relay — raw routes beside the typed contract. A rig must not accept
		// rig registrations, so this is gated rather than always-on.
		if (url.pathname.startsWith("/api/hub/")) {
			if (ROLE !== "hub")
				return new Response(JSON.stringify({ error: "not a hub" }), {
					status: 404,
					headers: { "content-type": "application/json" },
				});
			if (!hubAuthorized(request, url))
				return new Response(JSON.stringify({ error: "unauthorized" }), {
					status: 401,
					headers: { "content-type": "application/json" },
				});
			return handleHubRequest(request, url);
		}

		// A hub has no arm, no cameras and no lerobot cache. Gate the hardware
		// routes rather than let them spawn a driver that cannot exist there.
		if (
			ROLE === "hub" &&
			/^\/api\/(robot|cameras|record|cams)\b/.test(url.pathname)
		) {
			return new Response(
				JSON.stringify({ error: "this is a hub — no robot attached" }),
				{ status: 404, headers: { "content-type": "application/json" } },
			);
		}

		// MJPEG passthrough — outside the typed contract (infinite multipart stream)
		if (url.pathname.startsWith("/api/cams/")) {
			const name = url.pathname.split("/").at(-1);
			const base = mjpegBase();
			if (!base) return new Response("driver not ready", { status: 503 });
			const upstream = await fetch(`${base}/cam/${name}`);
			return new Response(upstream.body, {
				headers: {
					"content-type":
						upstream.headers.get("content-type") ?? "application/octet-stream",
					"cache-control": "no-store",
				},
			});
		}
		if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
			return apiHandler(request);
		}

		// Production static assets. `bun dist/server/server.js` has no vite in
		// front of it, and TanStack Start ships no static middleware — the SSR
		// HTML references /assets/* that would otherwise 404. dist/client sits
		// beside dist/server, so resolve relative to the bundle.
		if (
			!import.meta.env.DEV &&
			url.pathname.startsWith("/assets/") &&
			!url.pathname.includes("..")
		) {
			const file = Bun.file(
				new URL(`../client${url.pathname}`, import.meta.url).pathname,
			);
			if (await file.exists())
				return new Response(file, {
					headers: { "cache-control": "public, max-age=31536000, immutable" },
				});
		}

		// Headless: an agent is operated through the hub, never browsed directly.
		if (ROLE === "agent")
			return new Response("agent mode: no UI — drive this rig via the hub", {
				status: 404,
			});

		return startFetch(request);
	},
};
