import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import {
  cameraStatusQuery,
  confirmCameras,
  probeCameras,
  robotConnect,
  robotDisconnect,
  robotEstop,
  robotStateQuery,
  robotTeleopStart,
  robotTeleopStop,
  robotTorque,
  startPreview,
  stopPreview,
} from '#/lib/queries'

export const Route = createFileRoute('/robot')({ component: RobotPage })

function ArmPanel() {
  const state = useQuery(robotStateQuery)
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['robot'] })
  const [lastError, setLastError] = useState<string | null>(null)

  const useAct = (fn: () => Promise<unknown>) =>
    useMutation({
      mutationFn: fn,
      onSuccess: () => {
        setLastError(null)
        invalidate()
      },
      onError: (e) => setLastError(String(e)),
    })

  const connect = useAct(() => robotConnect(true))
  const connectSolo = useAct(() => robotConnect(false))
  const connectSim = useAct(() => robotConnect(false, 'sim'))
  const disconnect = useAct(robotDisconnect)
  const torqueOff = useAct(() => robotTorque(false))
  const torqueOn = useAct(() => robotTorque(true))
  const teleopStart = useAct(robotTeleopStart)
  const teleopStop = useAct(robotTeleopStop)
  const estop = useAct(robotEstop)

  const s = state.data
  const busy =
    connect.isPending || connectSolo.isPending || disconnect.isPending || teleopStart.isPending

  return (
    <div className="mt-8 rounded border p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            Arm{' '}
            {s?.backend === 'sim' && (
              <span className="mr-1 rounded bg-purple-600 px-1.5 py-0.5 text-xs font-bold text-white">
                SIM
              </span>
            )}
            <span
              className={
                s?.state === 'teleop'
                  ? 'text-blue-600'
                  : s?.state === 'connected'
                    ? 'text-green-600'
                    : 'text-muted-foreground'
              }
            >
              · {s?.state ?? '…'}
            </span>
          </h2>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">
            follower {s?.rig.followerPort} · leader {s?.rig.leaderPort} · id {s?.rig.robotId}
          </p>
        </div>
        <button
          type="button"
          className="rounded bg-red-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
          disabled={s?.state === 'disconnected'}
          onClick={() => estop.mutate()}
          title="Torque kill — arm goes limp, hold it if raised"
        >
          E-STOP
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-sm">
        {s?.state === 'disconnected' ? (
          <>
            <button
              type="button"
              className="rounded bg-foreground px-3 py-1.5 text-background disabled:opacity-50"
              disabled={busy}
              onClick={() => connect.mutate()}
            >
              {connect.isPending ? 'connecting…' : 'Connect (leader + follower)'}
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
              {connectSim.isPending ? 'loading MuJoCo…' : 'Connect SIM (MuJoCo)'}
            </button>
          </>
        ) : (
          <>
            {s?.state === 'connected' && s.leader && (
              <button
                type="button"
                className="rounded bg-foreground px-3 py-1.5 text-background disabled:opacity-50"
                disabled={busy}
                onClick={() => teleopStart.mutate()}
              >
                Start teleop
              </button>
            )}
            {s?.state === 'teleop' && (
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
  )
}

function RobotPage() {
  const status = useQuery(cameraStatusQuery)
  const queryClient = useQueryClient()
  const [probed, setProbed] = useState<ReadonlyArray<{ index: number; width: number; height: number }>>()
  const [workspace, setWorkspace] = useState<number | null>(null)
  const [wrist, setWrist] = useState<number | null>(null)

  const probe = useMutation({
    mutationFn: probeCameras,
    onSuccess: (cams) => setProbed(cams),
  })
  const preview = useMutation({
    mutationFn: (indexes: ReadonlyArray<number>) => startPreview(indexes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cameras'] }),
  })
  const stop = useMutation({
    mutationFn: stopPreview,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cameras'] }),
  })
  const confirm = useMutation({
    mutationFn: () => confirmCameras({ workspace, wrist }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cameras'] }),
  })

  const s = status.data
  const previewing = s?.previewing ?? []
  const band = s?.brightnessBand ?? { min: 115, max: 131 }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Robot</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        macOS shuffles camera indexes on replug: verify every session.
      </p>

      <ArmPanel />

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          className="rounded border px-3 py-1.5 text-sm"
          disabled={probe.isPending}
          onClick={() => probe.mutate()}
        >
          {probe.isPending ? 'probing…' : 'Probe cameras'}
        </button>
        {probed && probed.length > 0 && (
          <button
            type="button"
            className="rounded bg-foreground px-3 py-1.5 text-sm text-background"
            disabled={preview.isPending}
            onClick={() => preview.mutate(probed.map((c) => c.index))}
          >
            Start previews
          </button>
        )}
        {previewing.length > 0 && (
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm"
            onClick={() => stop.mutate()}
          >
            Stop previews
          </button>
        )}
      </div>

      {probe.isError && <p className="mt-2 text-sm text-red-500">{String(probe.error)}</p>}
      {probed && probed.length === 0 && (
        <p className="mt-2 text-sm text-amber-600">
          no cameras found — are they plugged in / not held by another app?
        </p>
      )}

      {previewing.length > 0 && (
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
          {previewing.map((name) => {
            const index = Number.parseInt(name.replace('cam', ''), 10)
            const bright = s?.brightness[name]
            const inBand = bright !== undefined && bright >= band.min && bright <= band.max
            return (
              <div key={name} className="rounded border p-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-mono">
                    {name}
                    {s?.mapping.workspace === index && ' · workspace ✓'}
                    {s?.mapping.wrist === index && ' · wrist ✓'}
                  </span>
                  {bright !== undefined && (
                    <span className={inBand ? 'text-green-600' : 'text-amber-600'}>
                      brightness {bright} {inBand ? '✓' : `(band ${band.min}–${band.max})`}
                    </span>
                  )}
                </div>
                {/* biome-ignore lint/performance/noImgElement: MJPEG stream needs plain img */}
                <img
                  src={`/api/cams/${name}`}
                  alt={name}
                  className="mt-2 w-full rounded bg-black"
                />
                <div className="mt-2 flex gap-2 text-sm">
                  <button
                    type="button"
                    className={`rounded border px-2 py-1 ${workspace === index ? 'bg-foreground text-background' : ''}`}
                    onClick={() => setWorkspace(index)}
                  >
                    this is workspace
                  </button>
                  <button
                    type="button"
                    className={`rounded border px-2 py-1 ${wrist === index ? 'bg-foreground text-background' : ''}`}
                    onClick={() => setWrist(index)}
                  >
                    this is wrist
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {previewing.length > 0 && (
        <button
          type="button"
          className="mt-4 rounded bg-foreground px-4 py-2 text-sm text-background disabled:opacity-50"
          disabled={workspace === null || wrist === null || workspace === wrist || confirm.isPending}
          onClick={() => confirm.mutate()}
        >
          Confirm mapping (workspace=cam{workspace ?? '?'} wrist=cam{wrist ?? '?'})
        </button>
      )}
      {confirm.isSuccess && <p className="mt-2 text-sm text-green-600">mapping saved to rig</p>}
    </div>
  )
}
