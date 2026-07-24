import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { PageHeader } from "#/components/page-header";
import { datasetEpisodesQuery } from "#/lib/queries";

export const Route = createFileRoute("/datasets_/$owner/$name")({
	component: DatasetReportPage,
});

function DatasetReportPage() {
	const { owner, name } = Route.useParams();
	const repoId = `${owner}/${name}`;
	const report = useQuery(datasetEpisodesQuery(repoId));
	const [excluded, setExcluded] = useState<ReadonlySet<number>>(new Set());

	const toggle = (index: number) => {
		const next = new Set(excluded);
		if (next.has(index)) next.delete(index);
		else next.add(index);
		setExcluded(next);
	};

	if (report.isPending)
		return <p className="text-muted-foreground">reading meta…</p>;
	if (report.isError)
		return <p className="text-red-500">failed: {String(report.error)}</p>;
	const r = report.data;

	const kept = r.episodes.map((e) => e.index).filter((i) => !excluded.has(i));
	const episodesArg = `[${kept.join(",")}]`;
	const flagged = r.episodes.filter((e) => e.flag !== null);

	return (
		<div>
			<PageHeader
				title={repoId}
				titleClassName="font-mono"
				back={{ to: "/datasets", label: "Datasets" }}
				description={
					<>
						{r.episodes.length} episodes · median {r.medianFrames ?? "—"} frames
						· {r.fps ?? "—"} fps
						{flagged.length > 0 && (
							<span className="text-amber-600">
								{" "}
								· {flagged.length} length outlier{flagged.length > 1 ? "s" : ""}
							</span>
						)}
					</>
				}
			/>

			{!r.local && (
				<p className="mt-4 text-sm text-amber-600">
					Not in the local cache — episode meta unavailable. Pull it locally
					(record/replay/train uses it) to see the report card.
				</p>
			)}

			{r.local && (
				<>
					<table className="mt-4 w-full max-w-3xl text-sm">
						<thead>
							<tr className="border-b text-left text-muted-foreground">
								<th className="py-2 pr-4">exclude</th>
								<th className="py-2 pr-4">ep</th>
								<th className="py-2 pr-4">frames</th>
								<th className="py-2 pr-4">seconds</th>
								<th className="py-2 pr-4">flag</th>
								<th className="py-2">task</th>
							</tr>
						</thead>
						<tbody>
							{r.episodes.map((e) => (
								<tr
									key={e.index}
									className={`border-b last:border-0 ${excluded.has(e.index) ? "opacity-40" : ""}`}
								>
									<td className="py-1.5 pr-4">
										<input
											type="checkbox"
											checked={excluded.has(e.index)}
											onChange={() => toggle(e.index)}
										/>
									</td>
									<td className="py-1.5 pr-4 font-mono">{e.index}</td>
									<td className="py-1.5 pr-4">{e.frames}</td>
									<td className="py-1.5 pr-4">{e.seconds}s</td>
									<td className="py-1.5 pr-4">
										{e.flag && (
											<span className="rounded bg-amber-500 px-1.5 py-0.5 text-xs font-bold text-white">
												{e.flag}
											</span>
										)}
									</td>
									<td className="py-1.5 text-muted-foreground">{e.task}</td>
								</tr>
							))}
						</tbody>
					</table>

					<div className="mt-6 max-w-3xl rounded border p-4 text-sm">
						<div className="font-medium">
							Train on kept episodes ({kept.length}/{r.episodes.length})
						</div>
						<p className="mt-1 text-xs text-muted-foreground">
							Never delete episodes from a dataset — exclude them at train time
							instead (delete_episodes is fragile on multi-resume datasets).
						</p>
						{excluded.size > 0 ? (
							<pre className="mt-2 overflow-x-auto rounded bg-muted p-3 font-mono text-xs">
								--dataset.episodes "{episodesArg}"
							</pre>
						) : (
							<p className="mt-2 text-xs text-muted-foreground">
								nothing excluded — training uses all episodes
							</p>
						)}
						<div className="mt-3 flex gap-2">
							{excluded.size > 0 && (
								<button
									type="button"
									className="rounded border px-3 py-1"
									onClick={() =>
										navigator.clipboard.writeText(
											`--dataset.episodes "${episodesArg}"`,
										)
									}
								>
									copy flag
								</button>
							)}
							<Link
								className="rounded bg-foreground px-3 py-1 text-background"
								to="/trainings/new"
								search={{
									dataset: repoId,
									episodes: excluded.size > 0 ? episodesArg : undefined,
								}}
							>
								use in new training
							</Link>
						</div>
					</div>
				</>
			)}
		</div>
	);
}
