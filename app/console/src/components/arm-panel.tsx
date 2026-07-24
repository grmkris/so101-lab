import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
	robotConnect,
	robotDisconnect,
	robotEstop,
	robotStateQuery,
	robotTeleopStart,
	robotTeleopStop,
	robotTorque,
} from "#/lib/queries";
import { KeyJogPad } from "./key-jog-pad";

export function ArmPanel() {
	const state = useQuery(robotStateQuery);
	const queryClient = useQueryClient();
	const invalidate = () =>
		queryClient.invalidateQueries({ queryKey: ["robot"] });
	const [lastError, setLastError] = useState<string | null>(null);

	const useAct = (fn: () => Promise<unknown>) =>
		useMutation({
			mutationFn: fn,
			onSuccess: () => {
				setLastError(null);
				invalidate();
			},
			onError: (e) => setLastError(String(e)),
		});

	const [source, setSource] = useState<string>("");
	const connect = useAct(() => robotConnect(true));
	const connectSolo = useAct(() => robotConnect(false));
	const connectSim = useAct(() => robotConnect(false, "sim"));
	const disconnect = useAct(robotDisconnect);
	const torqueOff = useAct(() => robotTorque(false));
	const torqueOn = useAct(() => robotTorque(true));
	const teleopStart = useAct(() =>
		robotTeleopStart(source === "" ? null : source),
	);
	const teleopStop = useAct(robotTeleopStop);
	const estop = useAct(robotEstop);

	const s = state.data;
	const busy =
		connect.isPending ||
		connectSolo.isPending ||
		disconnect.isPending ||
		teleopStart.isPending;

	return (
		<div className="mt-8 rounded border p-4">
			<div className="flex items-center justify-between">
				<div>
					<h2 className="text-lg font-semibold">
						Arm{" "}
						{s?.backend === "sim" && (
							<span className="mr-1 rounded bg-purple-600 px-1.5 py-0.5 text-xs font-bold text-white">
								SIM
							</span>
						)}
						<span
							className={
								s?.state === "teleop"
									? "text-blue-600"
									: s?.state === "connected"
										? "text-green-600"
										: "text-muted-foreground"
							}
						>
							· {s?.state ?? "…"}
						</span>
					</h2>
					<p className="mt-0.5 font-mono text-xs text-muted-foreground">
						follower {s?.rig.followerPort} · leader {s?.rig.leaderPort} · id{" "}
						{s?.rig.robotId}
					</p>
				</div>
				<button
					type="button"
					className="rounded bg-red-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
					disabled={s?.state === "disconnected"}
					onClick={() => estop.mutate()}
					title="Torque kill — arm goes limp, hold it if raised"
				>
					E-STOP
				</button>
			</div>

			<div className="mt-3 flex flex-wrap gap-2 text-sm">
				{s?.state === "disconnected" ? (
					<>
						<button
							type="button"
							className="rounded bg-foreground px-3 py-1.5 text-background disabled:opacity-50"
							disabled={busy}
							onClick={() => connect.mutate()}
						>
							{connect.isPending
								? "connecting…"
								: "Connect (leader + follower)"}
						</button>
						<button
							type="button"
							className="rounded border px-3 py-1.5 disabled:opacity-50"
							disabled={busy}
							onClick={() => connectSolo.mutate()}
						>
							Follower only
						</button>
						<button
							type="button"
							className="rounded border border-purple-600 px-3 py-1.5 text-purple-600 disabled:opacity-50"
							disabled={busy}
							onClick={() => connectSim.mutate()}
						>
							{connectSim.isPending
								? "loading MuJoCo…"
								: "Connect SIM (MuJoCo)"}
						</button>
					</>
				) : (
					<>
						{s?.state === "connected" && (
							<>
								<select
									className="rounded border bg-transparent px-2 py-1.5"
									value={source}
									onChange={(e) => setSource(e.target.value)}
								>
									<option value="">
										{s.backend === "sim"
											? "scripted (default)"
											: "leader (default)"}
									</option>
									{s.backend === "real" && (
										<option value="leader">leader arm</option>
									)}
									{s.backend === "sim" && (
										<option value="scripted">scripted expert</option>
									)}
									<option value="keys">keyboard (EE jog)</option>
								</select>
								<button
									type="button"
									className="rounded bg-foreground px-3 py-1.5 text-background disabled:opacity-50"
									disabled={busy}
									onClick={() => teleopStart.mutate()}
								>
									Start teleop
								</button>
							</>
						)}
						{s?.state === "teleop" && (
							<button
								type="button"
								className="rounded border px-3 py-1.5"
								onClick={() => teleopStop.mutate()}
							>
								Stop teleop
							</button>
						)}
						<button
							type="button"
							className="rounded border px-3 py-1.5"
							onClick={() => torqueOn.mutate()}
						>
							Torque on
						</button>
						<button
							type="button"
							className="rounded border px-3 py-1.5"
							onClick={() => torqueOff.mutate()}
						>
							Torque off
						</button>
						<button
							type="button"
							className="rounded border px-3 py-1.5"
							onClick={() => disconnect.mutate()}
						>
							Disconnect
						</button>
					</>
				)}
			</div>

			{lastError && <p className="mt-2 text-sm text-red-500">{lastError}</p>}

			{s?.state === "teleop" && s.source === "keys" && <KeyJogPad />}

			{s && Object.keys(s.joints).length > 0 && (
				<div className="mt-4 grid grid-cols-3 gap-2 font-mono text-xs md:grid-cols-6">
					{Object.entries(s.joints).map(([joint, pos]) => (
						<div key={joint} className="rounded bg-muted p-2">
							<div className="text-muted-foreground">{joint}</div>
							<div>{pos.toFixed(1)}</div>
						</div>
					))}
				</div>
			)}
		</div>
	);
}
