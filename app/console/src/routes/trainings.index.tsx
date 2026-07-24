import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { runsQuery } from "#/lib/queries";

export const Route = createFileRoute("/trainings/")({
	component: TrainingsPage,
});

const statusColor: Record<string, string> = {
	draft: "text-muted-foreground",
	launched: "text-blue-600",
	imported: "text-muted-foreground",
	done: "text-green-600",
	failed: "text-red-500",
};

function TrainingsPage() {
	const runs = useQuery(runsQuery);

	return (
		<div className="p-6">
			<div className="flex items-center justify-between">
				<div>
					<h1 className="text-2xl font-bold">Trainings</h1>
					<p className="mt-1 text-sm text-muted-foreground">
						Sidecar registry merged with kris0/* Hub models
					</p>
				</div>
				<Link
					to="/trainings/new"
					className="rounded bg-foreground px-3 py-1.5 text-sm text-background"
				>
					New training
				</Link>
			</div>

			{runs.isPending ? (
				<p className="mt-6 text-muted-foreground">loading…</p>
			) : runs.isError ? (
				<p className="mt-6 text-red-500">failed: {String(runs.error)}</p>
			) : (
				<table className="mt-6 w-full text-sm">
					<thead>
						<tr className="border-b text-left text-muted-foreground">
							<th className="py-2 pr-4">name</th>
							<th className="py-2 pr-4">status</th>
							<th className="py-2 pr-4">dataset</th>
							<th className="py-2 pr-4">steps</th>
							<th className="py-2 pr-4">created</th>
							<th className="py-2">hypothesis</th>
						</tr>
					</thead>
					<tbody>
						{runs.data.map((r) => (
							<tr key={r.id} className="border-b last:border-0">
								<td className="py-2 pr-4 font-mono">
									<Link
										className="underline"
										to="/trainings/$runId"
										params={{ runId: r.id }}
									>
										{r.name}
									</Link>
								</td>
								<td className={`py-2 pr-4 ${statusColor[r.status] ?? ""}`}>
									{r.status}
								</td>
								<td className="py-2 pr-4 font-mono">
									{r.config?.datasetRepoId ?? "—"}
								</td>
								<td className="py-2 pr-4">{r.config?.steps ?? "—"}</td>
								<td className="py-2 pr-4">
									{r.createdAt?.slice(0, 10) ?? "—"}
								</td>
								<td className="py-2 max-w-md truncate">
									{r.hypothesis ?? "—"}
								</td>
							</tr>
						))}
					</tbody>
				</table>
			)}
		</div>
	);
}
