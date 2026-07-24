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

const boot = globalThis as unknown as { __labRigLinkStarted?: boolean };
if (HUB_URL && process.env.LAB_MODE !== "hub" && !boot.__labRigLinkStarted) {
	boot.__labRigLinkStarted = true;
	startRigLink({ hubUrl: HUB_URL, rigName: RIG_NAME });
}

export default {
	async fetch(request: Request): Promise<Response> {
		const url = new URL(request.url);

		// Hub relay — raw routes beside the typed contract.
		if (url.pathname.startsWith("/api/hub/")) {
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
