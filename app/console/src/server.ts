import {
	createStartHandler,
	defaultStreamHandler,
} from "@tanstack/react-start/server";
import { apiHandler } from "#/api/live";
import { MJPEG_PORT } from "#/api/services/driver-manager";
import { handleHubRequest } from "#/hub/routes";
import { startRigLink } from "#/rig/link";

const startFetch = createStartHandler(defaultStreamHandler);

// LAB_MODE=hub -> no driver, serves the lobby + relays for registered rigs.
// Default (rig) is the existing local console; setting HUB_URL also registers
// it with a hub. Both modes run the same build.
const HUB_URL = process.env.HUB_URL;
const RIG_NAME = process.env.RIG_NAME ?? "local-rig";
const IS_HUB = process.env.LAB_MODE === "hub";

const boot = globalThis as unknown as { __labRigLinkStarted?: boolean };
if (HUB_URL && process.env.LAB_MODE !== "hub" && !boot.__labRigLinkStarted) {
	boot.__labRigLinkStarted = true;
	startRigLink({ hubUrl: HUB_URL, rigName: RIG_NAME });
}

export default {
	async fetch(request: Request): Promise<Response> {
		const url = new URL(request.url);

		// Which half of the app this process is. The two roles ship as one build
		// and differ only by env, so the client has to ask at runtime.
		if (url.pathname === "/api/mode") {
			return new Response(
				JSON.stringify({ mode: IS_HUB ? "hub" : "rig", rigName: RIG_NAME }),
				{ headers: { "content-type": "application/json" } },
			);
		}

		// Hub relay — raw routes beside the typed contract. A rig must not accept
		// rig registrations, so this is gated rather than always-on.
		if (url.pathname.startsWith("/api/hub/")) {
			if (!IS_HUB)
				return new Response(JSON.stringify({ error: "not a hub" }), {
					status: 404,
					headers: { "content-type": "application/json" },
				});
			return handleHubRequest(request, url);
		}

		// MJPEG passthrough — outside the typed contract (infinite multipart stream)
		if (url.pathname.startsWith("/api/cams/")) {
			const name = url.pathname.split("/").at(-1);
			const upstream = await fetch(
				`http://127.0.0.1:${MJPEG_PORT}/cam/${name}`,
			);
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
		return startFetch(request);
	},
};
