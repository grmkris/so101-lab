import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { healthQuery } from "#/lib/queries";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
	const health = useQuery(healthQuery);

	return (
		<div className="p-8">
			<h1 className="text-4xl font-bold">Lab Console</h1>
			<p className="mt-4 text-lg">
				API:{" "}
				{health.isPending ? (
					<span className="text-muted-foreground">checking…</span>
				) : health.isError ? (
					<span className="text-red-500">unreachable</span>
				) : (
					<span className="text-green-600">
						ok · hf user {health.data.hfUser} · v{health.data.version}
					</span>
				)}
			</p>
			<p className="mt-2 text-sm text-muted-foreground">
				<a className="underline" href="/api/docs">
					API docs
				</a>{" "}
				·{" "}
				<a className="underline" href="/api/openapi.json">
					openapi.json
				</a>
			</p>
		</div>
	);
}
