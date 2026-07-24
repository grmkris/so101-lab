import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Database } from "lucide-react";
import { ErrorNote } from "#/components/error-note";
import { PageHeader } from "#/components/page-header";
import { Button } from "#/components/ui/button";
import {
	Empty,
	EmptyContent,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from "#/components/ui/empty";
import { Skeleton } from "#/components/ui/skeleton";
import { datasetsQuery } from "#/lib/queries";

export const Route = createFileRoute("/datasets")({ component: DatasetsPage });

const STACK_VERSION = "v3.0"; // dataset codebase version written by lerobot 0.6.0

function DatasetsPage() {
	const datasets = useQuery(datasetsQuery);

	return (
		<div>
			<PageHeader
				title="Datasets"
				description="Local cache (~/.cache/huggingface/lerobot) merged with Hub (kris0/*)"
			/>

			{datasets.isPending ? (
				<div className="mt-6 flex flex-col gap-3">
					{[0, 1, 2].map((i) => (
						<Skeleton key={i} className="h-8 w-full" />
					))}
				</div>
			) : datasets.isError ? (
				<div className="mt-6">
					<ErrorNote error={datasets.error} />
				</div>
			) : datasets.data.length === 0 ? (
				<Empty className="mt-6 border">
					<EmptyHeader>
						<EmptyMedia variant="icon">
							<Database />
						</EmptyMedia>
						<EmptyTitle>No datasets yet</EmptyTitle>
						<EmptyDescription>
							Nothing in the local cache or on the Hub.
						</EmptyDescription>
					</EmptyHeader>
					<EmptyContent>
						<Button asChild>
							<Link to="/record">Record a session</Link>
						</Button>
					</EmptyContent>
				</Empty>
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
									{d.isLocal && (
										<>
											<Link
												className="underline"
												to="/datasets/$owner/$name"
												params={{
													owner: d.repoId.split("/")[0],
													name: d.repoId.split("/")[1],
												}}
											>
												report
											</Link>{" "}
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
