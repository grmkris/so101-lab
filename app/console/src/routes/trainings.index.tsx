import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Brain } from "lucide-react";
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
		<div>
			<PageHeader
				title="Trainings"
				description="Sidecar registry merged with kris0/* Hub models"
				actions={
					<Button asChild>
						<Link to="/trainings/new">New training</Link>
					</Button>
				}
			/>

			{runs.isPending ? (
				<div className="mt-6 flex flex-col gap-3">
					{[0, 1, 2].map((i) => (
						<Skeleton key={i} className="h-8 w-full" />
					))}
				</div>
			) : runs.isError ? (
				<div className="mt-6">
					<ErrorNote error={runs.error} />
				</div>
			) : runs.data.length === 0 ? (
				<Empty className="mt-6 border">
					<EmptyHeader>
						<EmptyMedia variant="icon">
							<Brain />
						</EmptyMedia>
						<EmptyTitle>No training runs yet</EmptyTitle>
						<EmptyDescription>
							Runs registered here track Hub checkpoints automatically.
						</EmptyDescription>
					</EmptyHeader>
					<EmptyContent>
						<Button asChild>
							<Link to="/trainings/new">New training</Link>
						</Button>
					</EmptyContent>
				</Empty>
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
