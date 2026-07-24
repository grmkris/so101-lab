import { type ChildProcess, spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import * as os from 'node:os'
import * as readline from 'node:readline'
import { Context, Effect, Layer } from 'effect'

const DRIVER_DIR = new URL('../../../../driver', import.meta.url).pathname
const VENV_PYTHON = `${DRIVER_DIR}/.venv/bin/python`
const PYTHON =
  process.env.LAB_DRIVER_PYTHON ??
  (existsSync(VENV_PYTHON) ? VENV_PYTHON : `${os.homedir()}/.local/share/uv/tools/lelab/bin/python`)
const DRIVER_SCRIPT = `${DRIVER_DIR}/driver.py`
export const MJPEG_PORT = 8765

export interface RecordState {
  active: boolean
  phase: string
  episode: number
  saved: number
  total: number
  repoId: string | null
}

interface Pending {
  resolve: (value: unknown) => void
  reject: (err: Error) => void
}

/**
 * Plain supervisor around the Python driver process. Lives on globalThis so
 * Vite HMR reloads never orphan or double-spawn the process.
 */
class DriverProc {
  private proc: ChildProcess | null = null
  private nextId = 1
  private pending = new Map<number, Pending>()
  brightness: Record<string, number> = {}
  streams: ReadonlyArray<string> = []
  readonly joints: Record<string, number> = {}
  robotState = 'disconnected'
  backendName = 'real'
  sourceName: string | null = null
  hasLeader = false
  recordState: RecordState = {
    active: false,
    phase: 'idle',
    episode: 0,
    saved: 0,
    total: 0,
    repoId: null,
  }
  private readyPromise: Promise<void> | null = null

  private start(): Promise<void> {
    if (this.readyPromise && this.proc && this.proc.exitCode === null) return this.readyPromise
    const proc = spawn(PYTHON, [DRIVER_SCRIPT, '--mjpeg-port', String(MJPEG_PORT)], {
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    this.proc = proc
    proc.stderr?.on('data', (chunk: Buffer) => console.error(chunk.toString().trimEnd()))
    proc.on('exit', (code) => {
      console.error(`[driver-manager] driver exited (${code})`)
      for (const p of this.pending.values()) p.reject(new Error(`driver exited (${code})`))
      this.pending.clear()
      this.proc = null
      this.readyPromise = null // next rpc() respawns lazily
      this.robotState = 'disconnected'
      this.backendName = 'real'
      this.sourceName = null
      this.hasLeader = false
      this.brightness = {}
      this.streams = []
    })

    this.readyPromise = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('driver did not become ready in 15s')), 15_000)
      const rl = readline.createInterface({ input: proc.stdout as NodeJS.ReadableStream })
      rl.on('line', (line) => {
        let msg: Record<string, unknown>
        try {
          msg = JSON.parse(line)
        } catch {
          console.error(`[driver-manager] non-json stdout: ${line}`)
          return
        }
        if (msg.event === 'ready') {
          clearTimeout(timer)
          resolve()
        } else if (msg.event === 'status') {
          this.brightness = msg.brightness as Record<string, number>
          this.streams = msg.streams as ReadonlyArray<string>
        } else if (msg.event === 'joints') {
          Object.assign(this.joints, msg.values as Record<string, number>)
        } else if (msg.event === 'robot_state') {
          this.robotState = String(msg.state)
          if (msg.backend) this.backendName = String(msg.backend)
          this.sourceName = msg.source ? String(msg.source) : null
        } else if (msg.event === 'record_state') {
          const phase = String(msg.phase)
          this.recordState = {
            active: phase === 'recording' || phase === 'resetting',
            phase,
            episode: Number(msg.episode),
            saved: Number(msg.saved),
            total: Number(msg.total),
            repoId: String(msg.repoId),
          }
        } else if (typeof msg.id === 'number') {
          const p = this.pending.get(msg.id)
          if (p) {
            this.pending.delete(msg.id)
            if (msg.ok) p.resolve(msg.result)
            else p.reject(new Error(String(msg.error)))
          }
        }
      })
    })
    return this.readyPromise
  }

  async rpc<T>(cmd: string, extra: Record<string, unknown> = {}): Promise<T> {
    await this.start()
    const proc = this.proc
    if (!proc?.stdin) throw new Error('driver not running')
    const id = this.nextId++
    const result = new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      setTimeout(() => {
        if (this.pending.delete(id)) reject(new Error(`driver rpc ${cmd} timed out (30s)`))
      }, 30_000)
    })
    proc.stdin.write(`${JSON.stringify({ id, cmd, ...extra })}\n`)
    return result as Promise<T>
  }

  kill(): void {
    this.proc?.kill()
    this.proc = null
    this.readyPromise = null
  }
}

const globalStore = globalThis as unknown as {
  __labDriverProc?: DriverProc
  __labDriverExitHook?: boolean
}
const driverProc = (globalStore.__labDriverProc ??= new DriverProc())

if (!globalStore.__labDriverExitHook) {
  globalStore.__labDriverExitHook = true
  for (const signal of ['exit', 'SIGINT', 'SIGTERM'] as const) {
    process.on(signal, () => {
      driverProc.kill()
      if (signal !== 'exit') process.exit(0)
    })
  }
}

export interface DriverManagerShape {
  readonly rpc: <T>(cmd: string, extra?: Record<string, unknown>) => Effect.Effect<T, Error>
  readonly brightness: () => Effect.Effect<Record<string, number>>
  readonly streams: () => Effect.Effect<ReadonlyArray<string>>
  readonly robot: () => Effect.Effect<{
    state: string
    backend: string
    source: string | null
    leader: boolean
    joints: Record<string, number>
  }>
  readonly record: () => Effect.Effect<RecordState>
  readonly setLeader: (leader: boolean) => Effect.Effect<void>
}

export class DriverManager extends Context.Service<DriverManager, DriverManagerShape>()(
  'app/DriverManager',
) {
  static readonly layer = Layer.succeed(DriverManager)({
    rpc: <T>(cmd: string, extra: Record<string, unknown> = {}) =>
      Effect.tryPromise({
        try: () => driverProc.rpc<T>(cmd, extra),
        catch: (e) => (e instanceof Error ? e : new Error(String(e))),
      }),
    brightness: () => Effect.sync(() => ({ ...driverProc.brightness })),
    streams: () => Effect.sync(() => driverProc.streams),
    robot: () =>
      Effect.sync(() => ({
        state: driverProc.robotState,
        backend: driverProc.backendName,
        source: driverProc.sourceName,
        leader: driverProc.hasLeader,
        joints: { ...driverProc.joints },
      })),
    record: () => Effect.sync(() => ({ ...driverProc.recordState })),
    setLeader: (leader: boolean) =>
      Effect.sync(() => {
        driverProc.hasLeader = leader
      }),
  })
}
