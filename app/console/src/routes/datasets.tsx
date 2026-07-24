import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { datasetsQuery } from "#/lib/queries";

export const Route = createFileRoute("/datasets")({ component: DatasetsPage });

const STACK_VERSION = "v3.0"; // dataset codebase version written by lerobot 0.6.0

function DatasetsPage() {
	const datasets = useQuery(datasetsQuery);

	return (
		<div className="p-6">
			<h1 className="text-2xl font-bold">Datasets</h1>
			<p className="mt-1 text-sm text-muted-foreground">
				Local cache (~/.cache/huggingface/lerobot) merged with Hub (kris0/*)
			</p>

			{datasets.isPending ? (
				<p className="mt-6 text-muted-foreground">scanning…</p>
			) : datasets.isError ? (
				<p className="mt-6 text-red-500">failed: {String(datasets.error)}</p>
			) : (
				<table className="mt-6 w-full text-sm">
					<thead>
						<tr className="border-b text-left text-muted-foreground">
							<th className="py-2 pr-4">repo</th>
							<th className="py-2 pr-4">episodes</th>
							<th className="py-2 pr-4">frames</th>
							<th className="py-2 pr-4">fps</th>
							<th className="py-2 pr-4">cameras</th>
							<th className="py-2 pr-4">format</th>
							<th className="py-2 pr-4">where</th>
							<th className="py-2">links</th>
						</tr>
					</thead>
					<tbody>
						{datasets.data.map((d) => (
							<tr key={d.repoId} className="border-b last:border-0">
								<td className="py-2 pr-4 font-mono">
									{d.repoId}
									{d.sim && (
										<span className="ml-2 rounded bg-purple-600 px-1.5 py-0.5 text-xs font-bold text-white">
											SIM
										</span>
									)}
								</td>
								<td className="py-2 pr-4">{d.totalEpisodes ?? "—"}</td>
								<td className="py-2 pr-4">{d.totalFrames ?? "—"}</td>
								<td className="py-2 pr-4">{d.fps ?? "—"}</td>
								<td className="py-2 pr-4">{d.cameras.join(", ") || "—"}</td>
								<td className="py-2 pr-4">
									{d.codebaseVersion ? (
										<span
											className={
												d.codebaseVersion === STACK_VERSION
													? "text-green-600"
													: "text-amber-600"
											}
											title={
												d.codebaseVersion === STACK_VERSION
													? "matches lerobot 0.6.0 stack"
													: `dataset format ${d.codebaseVersion} — verify against the 0.6.0 stack before training`
											}
										>
											{d.codebaseVersion}
										</span>
									) : (
										"—"
									)}
								</td>
								<td className="py-2 pr-4">
									{[d.isLocal ? "local" : null, d.onHub ? "hub" : null]
										.filter(Boolean)
										.join(" + ")}
								</td>
								<td className="py-2">
									{d.onHub && (
										<>
											<a
												className="underline"
												target="_blank"
												rel="noreferrer"
												href={`https://huggingface.co/datasets/${d.repoId}`}
											>
												hub
											</a>{" "}
											<a
												className="underline"
												target="_blank"
												rel="noreferrer"
												href={`https://huggingface.co/spaces/lerobot/visualize_dataset?dataset=${encodeURIComponent(d.repoId)}`}
											>
												visualize
											</a>{" "}
										</>
									)}
									<Link
										className="underline"
										to="/trainings/new"
										search={{ dataset: d.repoId }}
									>
										train
									</Link>
								</td>
							</tr>
						))}
					</tbody>
				</table>
			)}
		</div>
	);
}
