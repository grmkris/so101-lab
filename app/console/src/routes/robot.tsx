import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import {
  cameraStatusQuery,
  confirmCameras,
  probeCameras,
  robotConnect,
  robotDisconnect,
  robotEstop,
  robotStateQuery,
  robotTeleopInput,
  robotTeleopStart,
  robotTeleopStop,
  robotTorque,
  startPreview,
  stopPreview,
} from '#/lib/queries'

export const Route = createFileRoute('/robot')({ component: RobotPage })

// browser-side key → EE axis map (lerobot units downstream; no pynput, no OS permissions)
const KEY_AXES: Record<string, [string, number]> = {
  w: ['x', 1],
  s: ['x', -1],
  a: ['y', 1],
  d: ['y', -1],
  q: ['z', 1],
  e: ['z', -1],
  o: ['gripper', 1],
  c: ['gripper', -1],
}

function KeyJogPad() {
  const pressed = useRef<Record<string, number>>({})
  const [focused, setFocused] = useState(false)

  const send = () => {
    const axes: Record<string, number> = { x: 0, y: 0, z: 0, gripper: 0 }
    for (const [key, [axis, sign]] of Object.entries(KEY_AXES)) {
      if (pressed.current[key]) axes[axis] += sign
    }
    for (const k of Object.keys(axes)) axes[k] = Math.max(-1, Math.min(1, axes[k]))
    robotTeleopInput(axes).catch(() => {})
  }

  useEffect(() => {
    // heartbeat keeps the driver's deadman fed while keys are held
    const interval = setInterval(() => {
      if (Object.values(pressed.current).some(Boolean)) send()
    }, 200)
    return () => clearInterval(interval)
  }, [])

  return (
    // biome-ignore lint/a11y/noNoninteractiveTabindex: intentional key-capture surface
    <div
      tabIndex={0}
      onFocus={() => setFocused(true)}
      onBlur={() => {
        setFocused(false)
        pressed.current = {}
        send()
      }}
      onKeyDown={(e) => {
        const key = e.key.toLowerCase()
        if (key in KEY_AXES) {
          e.preventDefault()
          if (!pressed.current[key]) {
            pressed.current[key] = 1
            send()
          }
        }
      }}
      onKeyUp={(e) => {
        const key = e.key.toLowerCase()
        if (key in KEY_AXES) {
          pressed.current[key] = 0
          send()
        }
      }}
      className={`mt-3 cursor-pointer rounded border-2 p-4 text-sm outline-none ${
        focused ? 'border-blue-600 bg-blue-600/5' : 'border-dashed'
      }`}
    >
      <div className="font-medium">
        {focused ? '⌨ capturing keys — arm is live' : 'click here to grab the keyboard'}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1 font-mono text-xs text-muted-foreground md:grid-cols-4">
        <span>W/S forward · back</span>
        <span>A/D left · right</span>
        <span>Q/E up · down</span>
        <span>O/C gripper open · close</span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        release all keys (or click away) → arm holds pose (0.5&nbsp;s deadman)
      </p>
    </div>
  )
}

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

  const [source, setSource] = useState<string>('')
  const connect = useAct(() => robotConnect(true))
  const connectSolo = useAct(() => robotConnect(false))
  const connectSim = useAct(() => robotConnect(false, 'sim'))
  const disconnect = useAct(robotDisconnect)
  const torqueOff = useAct(() => robotTorque(false))
  const torqueOn = useAct(() => robotTorque(true))
  const teleopStart = useAct(() => robotTeleopStart(source === '' ? null : source))
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
            {s?.state === 'connected' && (
              <>
                <select
                  className="rounded border bg-transparent px-2 py-1.5"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="">
                    {s.backend === 'sim' ? 'scripted (default)' : 'leader (default)'}
                  </option>
                  {s.backend === 'real' && <option value="leader">leader arm</option>}
                  {s.backend === 'sim' && <option value="scripted">scripted expert</option>}
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

      {s?.state === 'teleop' && s.source === 'keys' && <KeyJogPad />}

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
