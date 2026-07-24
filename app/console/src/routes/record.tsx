import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { recordControl, recordStart, recordStatusQuery, robotStateQuery } from '#/lib/queries'

export const Route = createFileRoute('/record')({ component: RecordPage })

const ts = () => {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

function RecordPage() {
  const robot = useQuery(robotStateQuery)
  const status = useQuery(recordStatusQuery)
  const queryClient = useQueryClient()

  const backend = robot.data?.backend ?? 'real'
  const isSim = backend === 'sim'

  const [repoName, setRepoName] = useState(`so101_${isSim ? 'sim' : 'session'}_${ts()}`)
  const [task, setTask] = useState('pick the piece and place it on the peg')
  const [numEpisodes, setNumEpisodes] = useState(5)
  const [episodeS, setEpisodeS] = useState(20)
  const [resetS, setResetS] = useState(10)

  const start = useMutation({
    mutationFn: () =>
      recordStart({ repoName, task, numEpisodes, episodeS, resetS, resume: false }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['record'] }),
  })
  const control = useMutation({
    mutationFn: recordControl,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['record'] }),
  })

  const s = status.data
  const active = s?.active ?? false
  const field = 'mt-1 w-full rounded border bg-transparent px-2 py-1.5 text-sm'
  const label = 'mt-3 block text-sm font-medium'

  return (
    <div className="p-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">Record</h1>
        <span
          className={`rounded px-2 py-0.5 text-xs font-bold ${isSim ? 'bg-purple-600 text-white' : 'bg-muted'}`}
        >
          {backend.toUpperCase()}
        </span>
        <span className="text-sm text-muted-foreground">
          arm: {robot.data?.state ?? '…'}
        </span>
      </div>

      {robot.data?.state === 'disconnected' && (
        <p className="mt-4 text-sm text-amber-600">
          Connect on the Robot page first (real arm or SIM).
        </p>
      )}

      {!active && robot.data?.state !== 'disconnected' && (
        <div className="mt-4 max-w-xl rounded border p-4">
          <label className={label}>
            Dataset name (kris0/…)
            <input className={field} value={repoName} onChange={(e) => setRepoName(e.target.value)} />
          </label>
          <label className={label}>
            Task
            <input className={field} value={task} onChange={(e) => setTask(e.target.value)} />
          </label>
          <div className="flex gap-3">
            <label className={label}>
              Episodes
              <input
                type="number"
                className={field}
                value={numEpisodes}
                onChange={(e) => setNumEpisodes(Number(e.target.value))}
              />
            </label>
            <label className={label}>
              Episode s
              <input
                type="number"
                className={field}
                value={episodeS}
                onChange={(e) => setEpisodeS(Number(e.target.value))}
              />
            </label>
            <label className={label}>
              Reset s
              <input
                type="number"
                className={field}
                value={resetS}
                onChange={(e) => setResetS(Number(e.target.value))}
              />
            </label>
          </div>
          {!isSim && (
            <p className="mt-3 text-xs text-muted-foreground">
              Real recording needs the leader arm connected and cameras confirmed (Robot page).
              Episode saves on timeout or “keep”.
            </p>
          )}
          <button
            type="button"
            className="mt-4 rounded bg-foreground px-4 py-2 text-sm text-background disabled:opacity-50"
            disabled={start.isPending || !repoName || !task}
            onClick={() => start.mutate()}
          >
            {start.isPending ? 'starting…' : `Start recording (${numEpisodes} eps)`}
          </button>
          {start.isError && (
            <p
              className={`mt-2 text-sm ${
                String(start.error).includes('PreflightError') ? 'text-amber-600' : 'text-red-500'
              }`}
            >
              {String(start.error)}
            </p>
          )}
        </div>
      )}

      {active && s && (
        <div className="mt-4">
          <div className="flex items-center gap-4">
            <span
              className={`rounded px-3 py-1 text-sm font-bold ${
                s.phase === 'recording' ? 'bg-red-600 text-white' : 'bg-amber-500 text-white'
              }`}
            >
              {s.phase === 'recording' ? '● REC' : 'RESET'}
            </span>
            <span className="font-mono text-lg">
              episode {s.episode}/{s.total} · saved {s.saved}
            </span>
            <span className="font-mono text-sm text-muted-foreground">{s.repoId}</span>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            {['workspace_cam', 'wrist_cam'].map((cam) => (
              <div key={cam} className="rounded border p-2">
                <div className="font-mono text-xs text-muted-foreground">{cam}</div>
                {isSim ? (
                  // biome-ignore lint/performance/noImgElement: MJPEG stream
                  <img src={`/api/cams/${cam}`} alt={cam} className="mt-1 w-full rounded bg-black" />
                ) : (
                  <p className="mt-1 p-4 text-xs text-muted-foreground">
                    cameras are owned by the recorder during real sessions
                  </p>
                )}
              </div>
            ))}
          </div>

          <div className="mt-4 flex gap-2">
            <button
              type="button"
              className="rounded bg-foreground px-4 py-2 text-sm text-background"
              onClick={() => control.mutate('keep')}
            >
              ✓ keep &amp; next
            </button>
            <button
              type="button"
              className="rounded border px-4 py-2 text-sm"
              onClick={() => control.mutate('rerecord')}
            >
              ↺ re-record
            </button>
            <button
              type="button"
              className="rounded border border-red-600 px-4 py-2 text-sm text-red-600"
              onClick={() => control.mutate('finish')}
            >
              ■ finish
            </button>
          </div>
        </div>
      )}

      {!active && s && (s.phase === 'done' || s.phase === 'failed') && (
        <div className="mt-4 rounded border p-4 text-sm">
          <p className={s.phase === 'done' ? 'text-green-600' : 'text-red-500'}>
            last session: {s.phase} — {s.saved}/{s.total} episodes saved
            {s.repoId && <span className="font-mono"> · {s.repoId}</span>}
          </p>
        </div>
      )}
    </div>
  )
}
