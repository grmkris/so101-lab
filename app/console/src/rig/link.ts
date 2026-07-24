/**
 * Rig → hub link. Dials OUT, so the rig needs no inbound port, no port
 * forwarding and no public IP — the same reason lerobot's async-inference
 * client dials out to its policy server.
 *
 * Plain HTTP polling rather than a socket: it behaves identically in vite dev
 * and in production, survives a Railway redeploy with no reconnect logic, and
 * is debuggable with curl. One request carries telemetry up and control down.
 */
import { apiHandler } from "#/api/live";
import { mjpegBase } from "#/api/services/driver-manager";

const LINK_MS = 50; // 20 Hz control
const FRAME_MS = 125; // 8 fps preview — the recording stays full-rate locally
// sim renders to these fixed names; a real rig names them cam0/cam1 and only
// knows which exist once previews are running, so the list is discovered
const SIM_CAMS = ["workspace_cam", "wrist_cam"];

/** Call the rig's own API in-process — reuses all existing validation. */
const localApi = async (
	path: string,
	init?: RequestInit,
): Promise<unknown | null> => {
	try {
		const res = await apiHandler(
			new Request(`http://rig.local${path}`, {
				...init,
				headers: { "content-type": "application/json", ...init?.headers },
			}),
		);
		if (!res.ok) return null;
		return await res.json();
	} catch {
		return null;
	}
};

interface RobotState {
	state: string;
	backend: string;
	source: string | null;
	joints: Record<string, number>;
	lastError: string | null;
}

export const startRigLink = (opts: {
	hubUrl: string;
	rigName: string;
	/** "sim" | "real" — bring the backend up on boot so the rig appears in the
	 * lobby already streaming, instead of waiting for someone to click Connect. */
	autoConnect?: string;
}): void => {
	const { hubUrl, rigName, autoConnect } = opts;
	const base = hubUrl.replace(/\/$/, "");
	let cams: string[] = [];
	let previewing: ReadonlyArray<string> = [];
	let linkMs = 0;
	let warned = false;

	let autoConnectTried = false;
	const link = async () => {
		const started = Date.now();
		const robot = (await localApi("/api/robot/state")) as RobotState | null;

		if (autoConnect && !autoConnectTried && robot?.state === "disconnected") {
			autoConnectTried = true; // one attempt — never fight a human disconnect
			console.error(`[rig-link] auto-connecting backend=${autoConnect}`);
			await localApi("/api/robot/connect", {
				method: "POST",
				body: JSON.stringify({ withLeader: true, backend: autoConnect }),
			});
			if (autoConnect === "real") {
				const cams = (await localApi("/api/cameras/probe")) as Array<{
					index: number;
				}> | null;
				if (cams?.length)
					await localApi("/api/cameras/preview/start", {
						method: "POST",
						body: JSON.stringify({ indexes: cams.map((c) => c.index) }),
					});
			}
		}
		const cameras = (await localApi("/api/cameras/status")) as {
			previewing?: string[];
		} | null;
		previewing = cameras?.previewing ?? [];
		const advertised = cams.length > 0 ? cams : previewing;

		try {
			const res = await fetch(`${base}/api/hub/link`, {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({
					name: rigName,
					backend: robot?.backend ?? "real",
					armState: robot?.state ?? "disconnected",
					source: robot?.source ?? null,
					joints: robot?.joints ?? {},
					cams: advertised,
					lastError: robot?.lastError ?? null,
					linkMs,
				}),
			});
			linkMs = Date.now() - started;
			if (!res.ok) return;
			const body = (await res.json()) as {
				input: Record<string, number> | null;
				commands: Array<{ verb: string }>;
			};
			warned = false;

			if (body.input) {
				await localApi("/api/robot/teleop/input", {
					method: "POST",
					body: JSON.stringify({ axes: body.input }),
				});
			}
			for (const cmd of body.commands ?? []) {
				await runCommand(cmd.verb);
			}
		} catch (err) {
			if (!warned) {
				warned = true;
				console.error(
					`[rig-link] hub unreachable at ${base} (${String(err)}) — retrying`,
				);
			}
		}
	};

	const runCommand = async (verb: string) => {
		switch (verb) {
			case "connect_sim":
				// withLeader so a physical leader arm can drive the sim
				await localApi("/api/robot/connect", {
					method: "POST",
					body: JSON.stringify({ withLeader: true, backend: "sim" }),
				});
				break;
			case "connect_real":
				await localApi("/api/robot/connect", {
					method: "POST",
					body: JSON.stringify({ withLeader: true, backend: "real" }),
				});
				break;
			case "teleop_start":
				await localApi("/api/robot/teleop/start", {
					method: "POST",
					body: JSON.stringify({ source: "keys" }),
				});
				break;
			case "teleop_start_leader":
				await localApi("/api/robot/teleop/start", {
					method: "POST",
					body: JSON.stringify({ source: "leader" }),
				});
				break;
			case "teleop_stop":
				await localApi("/api/robot/teleop/stop", { method: "POST" });
				break;
			case "estop":
				await localApi("/api/robot/estop", { method: "POST" });
				break;
			case "disconnect":
				await localApi("/api/robot/disconnect", { method: "POST" });
				break;
			default:
				console.error(`[rig-link] unknown command ${verb}`);
		}
	};

	const pushFrames = async () => {
		const found: string[] = [];
		const candidates = [...new Set([...previewing, ...SIM_CAMS])];
		for (const cam of candidates) {
			try {
				const mjpeg = mjpegBase(); // NOT `base` — that is the hub URL
				if (!mjpeg) break;
				const snap = await fetch(`${mjpeg}/snap/${cam}`);
				if (!snap.ok) continue;
				found.push(cam);
				const buf = await snap.arrayBuffer();
				const res = await fetch(
					`${base}/api/hub/frame?rig=${encodeURIComponent(rigName)}&cam=${encodeURIComponent(cam)}`,
					{
						method: "POST",
						headers: { "content-type": "image/jpeg" },
						body: buf,
					},
				);
				if (!res.ok)
					console.error(
						`[rig-link] hub rejected frame ${cam}: ${res.status} ${await res.text()}`,
					);
			} catch (err) {
				console.error(
					`[rig-link] frame push failed for ${cam}: ${String(err)}`,
				);
			}
		}
		cams = found;
	};

	console.error(`[rig-link] ${rigName} -> ${base} (link ${LINK_MS}ms)`);
	setInterval(() => void link(), LINK_MS);
	setInterval(() => void pushFrames(), FRAME_MS);
};
