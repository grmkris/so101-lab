import { queryOptions } from "@tanstack/react-query";

export interface RigSummary {
	name: string;
	backend: string;
	armState: string;
	source: string | null;
	online: boolean;
	cams: ReadonlyArray<string>;
	joints: Record<string, number>;
	holder: string | null;
	linkMs: number;
	lastSeen: number;
}

/** One id per browser tab — the lease is held by this, not by a user account. */
export const clientId = ((): string => {
	if (typeof window === "undefined") return "ssr";
	const key = "lab-client-id";
	let id = sessionStorage.getItem(key);
	if (!id) {
		id = `op-${Math.random().toString(36).slice(2, 10)}`;
		sessionStorage.setItem(key, id);
	}
	return id;
})();

const post = async (path: string, body: Record<string, unknown> = {}) => {
	const res = await fetch(path, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ clientId, ...body }),
	});
	const json = (await res.json().catch(() => ({}))) as Record<string, unknown>;
	if (!res.ok) throw new Error(String(json.error ?? res.statusText));
	return json;
};

export const rigsQuery = queryOptions({
	queryKey: ["hub", "rigs"],
	queryFn: async (): Promise<ReadonlyArray<RigSummary>> => {
		const res = await fetch("/api/hub/rigs");
		if (!res.ok) throw new Error("hub unreachable");
		return res.json();
	},
	refetchInterval: 2_000,
});

export const rigQuery = (name: string) =>
	queryOptions({
		queryKey: ["hub", "rigs", name],
		queryFn: async (): Promise<RigSummary> => {
			const res = await fetch(`/api/hub/rigs/${encodeURIComponent(name)}`);
			if (!res.ok) throw new Error("rig not registered on this hub");
			return res.json();
		},
		refetchInterval: 500,
	});

export const impairmentQuery = queryOptions({
	queryKey: ["hub", "impairment"],
	queryFn: async (): Promise<{ latencyMs: number; dropRate: number }> => {
		const res = await fetch("/api/hub/impairment");
		return res.json();
	},
	staleTime: 60_000,
});

export const claimRig = (name: string) =>
	post(`/api/hub/rigs/${encodeURIComponent(name)}/claim`);
export const releaseRig = (name: string) =>
	post(`/api/hub/rigs/${encodeURIComponent(name)}/release`);
export const sendRigInput = (name: string, axes: Record<string, number>) =>
	post(`/api/hub/rigs/${encodeURIComponent(name)}/input`, { axes });
export const sendRigCommand = (name: string, verb: string) =>
	post(`/api/hub/rigs/${encodeURIComponent(name)}/command`, { verb });
