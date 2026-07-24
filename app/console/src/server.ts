import {
	createStartHandler,
	defaultStreamHandler,
} from "@tanstack/react-start/server";
import { apiHandler } from "#/api/live";
import { MJPEG_PORT } from "#/api/services/driver-manager";

const startFetch = createStartHandler(defaultStreamHandler);

export default {
	async fetch(request: Request): Promise<Response> {
		const url = new URL(request.url);
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
