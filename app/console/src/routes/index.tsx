import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
	cameraStatusQuery,
	datasetsQuery,
	healthQuery,
	robotStateQuery,
	runsQuery,
} from "#/lib/queries";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
	const health = useQuery(healthQuery);
	const robot = useQuery(robotStateQuery);
	const cams = useQuery(cameraStatusQuery);
	const datasets = useQuery(datasetsQuery);
	const runs = useQuery(runsQuery);

	const r = robot.data;
	const c = cams.data;
	const latestDataset = datasets.data?.[0];
	const launched = (runs.data ?? []).filter((x) => x.status === "launched");
	const card = "rounded border p-4 text-sm";

	return (
		<div className="p-6">
			<div className="flex items-baseline gap-3">
				<h1 className="text-3xl font-bold">Lab Console</h1>
				<span className="text-sm text-muted-foreground">
					{health.isPending
						? "checking…"
						: health.isError
							? "API unreachable"
							: `hf ${health.data.hfUser} · v${health.data.version}`}
				</span>
			</div>

			<div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
				<div className={card}>
					<div className="flex items-center justify-between">
						<span className="font-medium">Rig</span>
						<Link className="underline" to="/robot">
							robot page
						</Link>
					</div>
					<p className="mt-2">
						arm:{" "}
						<span
							className={
								r?.state === "disconnected"
									? "text-muted-foreground"
									: "text-green-600"
							}
						>
							{r?.state ?? "…"}
						</span>
						{r && r.state !== "disconnected" && (
							<span className="text-muted-foreground">
								{" "}
								· {r.backend}
								{r.source ? ` · ${r.source}` : ""}
								{r.backend === "real" && !r.leader ? " · no leader" : ""}
							</span>
						)}
					</p>
					<p className="mt-1 text-muted-foreground">
						cameras:{" "}
						{c
							? c.previewing.length > 0
								? c.previewing
										.map((name) => {
											const b = c.brightness[name];
											const inBand =
												b !== undefined &&
												b >= c.brightnessBand.min &&
												b <= c.brightnessBand.max;
											return `${name} (${b ?? "…"}${b !== undefined ? (inBand ? " ✓" : " ⚠") : ""})`;
										})
										.join(" · ")
								: c.mapping.workspace !== null && c.mapping.wrist !== null
									? "confirmed, not previewing"
									: "not confirmed — verify indexes before a session"
							: "…"}
					</p>
				</div>

				<div className={card}>
					<div className="flex items-center justify-between">
						<span className="font-medium">Trainings in flight</span>
						<Link className="underline" to="/trainings">
							all runs
						</Link>
					</div>
					{launched.length === 0 ? (
						<p className="mt-2 text-muted-foreground">
							none launched —{" "}
							<Link className="underline" to="/trainings/new">
								start one
							</Link>
						</p>
					) : (
						<ul className="mt-2 space-y-1">
							{launched.map((run) => (
								<li key={run.id} className="font-mono">
									<Link
										className="underline"
										to="/trainings/$runId"
										params={{ runId: run.id }}
									>
										{run.name}
									</Link>
									{run.config && (
										<span className="text-muted-foreground">
											{" "}
											· {run.config.steps} steps
										</span>
									)}
								</li>
							))}
						</ul>
					)}
				</div>

				<div className={card}>
					<div className="flex items-center justify-between">
						<span className="font-medium">Latest dataset</span>
						<Link className="underline" to="/datasets">
							all datasets
						</Link>
					</div>
					{latestDataset ? (
						<p className="mt-2 font-mono">
							{latestDataset.repoId}
							<span className="text-muted-foreground">
								{latestDataset.totalEpisodes
									? ` · ${latestDataset.totalEpisodes} eps`
									: ""}
								{latestDataset.sim ? " · SIM" : ""}
							</span>
						</p>
					) : (
						<p className="mt-2 text-muted-foreground">none yet</p>
					)}
					<p className="mt-1">
						<Link className="underline" to="/record">
							record a session
						</Link>
					</p>
				</div>

				<div className={card}>
					<span className="font-medium">API</span>
					<p className="mt-2 text-muted-foreground">
						<a className="underline" href="/api/docs">
							docs
						</a>{" "}
						·{" "}
						<a className="underline" href="/api/openapi.json">
							openapi.json
						</a>
					</p>
				</div>
			</div>
		</div>
	);
}
