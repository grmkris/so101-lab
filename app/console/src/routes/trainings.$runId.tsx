import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { checkpointsQuery, patchRun, runQuery } from "#/lib/queries";

export const Route = createFileRoute("/trainings/$runId")({
	component: RunPage,
});

function RunPage() {
	const { runId } = Route.useParams();
	const run = useQuery(runQuery(runId));
	const checkpoints = useQuery(checkpointsQuery(runId));
	const queryClient = useQueryClient();
	const [finding, setFinding] = useState<string | null>(null);

	const saveFinding = useMutation({
		mutationFn: (value: string) =>
			patchRun(runId, { status: null, hypothesis: null, finding: value }),
		onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
	});

	const markLaunched = useMutation({
		mutationFn: () =>
			patchRun(runId, { status: "launched", hypothesis: null, finding: null }),
		onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
	});

	if (run.isPending)
		return <p className="p-6 text-muted-foreground">loading…</p>;
	if (run.isError)
		return <p className="p-6 text-red-500">failed: {String(run.error)}</p>;
	const r = run.data;

	const targetSteps = r.config?.steps ?? null;
	const ckptSteps = checkpoints.data?.steps ?? [];
	const lastCkpt = ckptSteps.at(-1)
		? Number.parseInt(ckptSteps.at(-1) as string, 10)
		: 0;
	const progress = targetSteps
		? Math.min(100, Math.round((lastCkpt / targetSteps) * 100))
		: null;

	return (
		<div className="max-w-3xl p-6">
			<h1 className="font-mono text-2xl font-bold">{r.name}</h1>
			<p className="mt-1 text-sm text-muted-foreground">
				{r.status} · {r.hubModelId} ·{" "}
				<a
					className="underline"
					target="_blank"
					rel="noreferrer"
					href={`https://huggingface.co/${r.hubModelId}`}
				>
					hub
				</a>
			</p>

			{r.config && (
				<div className="mt-4 rounded border p-4 text-sm">
					<div className="font-medium">Lineage</div>
					<div className="mt-1 font-mono text-muted-foreground">
						dataset {r.config.datasetRepoId}
						{r.config.episodes
							? ` · episodes ${r.config.episodes}`
							: " · all episodes"}
						{r.config.pretrainedPath
							? ` · warm-start ${r.config.pretrainedPath}`
							: " · from scratch"}
					</div>
					<div className="mt-1 text-muted-foreground">
						{r.config.steps} steps · batch {r.config.batchSize} · save every{" "}
						{r.config.saveFreq}
					</div>
				</div>
			)}

			<div className="mt-4 rounded border p-4 text-sm">
				<div className="font-medium">Checkpoints on Hub</div>
				{checkpoints.isPending ? (
					<p className="mt-1 text-muted-foreground">polling…</p>
				) : ckptSteps.length === 0 ? (
					<p className="mt-1 text-muted-foreground">
						none yet — appear every save_freq steps once training runs
					</p>
				) : (
					<div className="mt-2">
						<div className="font-mono text-muted-foreground">
							{ckptSteps.join(" · ")}
						</div>
						{progress !== null && (
							<div className="mt-2 h-2 w-full rounded bg-muted">
								<div
									className="h-2 rounded bg-foreground"
									style={{ width: `${progress}%` }}
								/>
							</div>
						)}
					</div>
				)}
			</div>

			{r.hypothesis && (
				<div className="mt-4 rounded border p-4 text-sm">
					<div className="font-medium">Hypothesis</div>
					<p className="mt-1">{r.hypothesis}</p>
				</div>
			)}

			{r.status !== "imported" && (
				<div className="mt-4 rounded border p-4 text-sm">
					<div className="font-medium">Finding (after eval)</div>
					<textarea
						className="mt-2 w-full rounded border bg-transparent px-2 py-1.5 font-sans text-sm"
						rows={2}
						defaultValue={r.finding ?? ""}
						onChange={(e) => setFinding(e.target.value)}
						placeholder="what did this run teach you?"
					/>
					<button
						type="button"
						className="mt-2 rounded bg-foreground px-3 py-1 text-background disabled:opacity-50"
						disabled={finding === null || saveFinding.isPending}
						onClick={() => finding !== null && saveFinding.mutate(finding)}
					>
						save
					</button>
				</div>
			)}

			{r.colabCell && (
				<div className="mt-4 rounded border p-4 text-sm">
					<div className="flex items-center justify-between">
						<div className="font-medium">Colab cell (version-matched)</div>
						<div className="flex gap-2">
							<button
								type="button"
								className="rounded border px-3 py-1"
								onClick={() =>
									navigator.clipboard.writeText(r.colabCell as string)
								}
							>
								copy
							</button>
							{r.status === "draft" && (
								<button
									type="button"
									className="rounded bg-foreground px-3 py-1 text-background"
									onClick={() => markLaunched.mutate()}
								>
									mark launched
								</button>
							)}
						</div>
					</div>
					<pre className="mt-2 overflow-x-auto rounded bg-muted p-3 font-mono text-xs">
						{r.colabCell}
					</pre>
				</div>
			)}
		</div>
	);
}
