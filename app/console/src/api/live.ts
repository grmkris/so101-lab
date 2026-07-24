import { NodeFileSystem } from '@effect/platform-node'
import { Effect, Layer, Path } from 'effect'
import { Etag, FetchHttpClient, HttpPlatform, HttpRouter } from 'effect/unstable/http'
import { HttpApiBuilder, HttpApiScalar } from 'effect/unstable/httpapi'
import { Checkpoints, DriverError, HealthStatus, HfStatus, LabApi, RobotState } from './contract'
import { RIG } from './rig'
import { Cameras } from './services/cameras'
import { DatasetCatalog } from './services/dataset-catalog'
import { DriverManager } from './services/driver-manager'
import { HfHub } from './services/hf-hub'
import { Recorder } from './services/record'
import { RunsRegistry } from './services/runs-registry'

const HealthLive = HttpApiBuilder.group(LabApi, 'Health', (handlers) =>
  handlers.handle('status', () =>
    Effect.succeed(new HealthStatus({ ok: true, hfUser: 'kris0', version: '0.1.0' })),
  ),
)

const HfLive = HttpApiBuilder.group(LabApi, 'Hf', (handlers) =>
  handlers.handle('status', () =>
    Effect.flatMap(HfHub, (hub) => hub.status()).pipe(
      Effect.map((s) => new HfStatus(s)),
    ),
  ),
)

const DatasetsLive = HttpApiBuilder.group(LabApi, 'Datasets', (handlers) =>
  handlers.handle('list', () =>
    Effect.flatMap(DatasetCatalog, (catalog) => catalog.list()),
  ),
)

const TrainingsLive = HttpApiBuilder.group(LabApi, 'Trainings', (handlers) =>
  handlers
    .handle('list', () => Effect.flatMap(RunsRegistry, (r) => r.list()))
    .handle('get', ({ params }) =>
      Effect.flatMap(RunsRegistry, (r) => r.get(params.id)).pipe(Effect.orDie),
    )
    .handle('create', ({ payload }) =>
      Effect.flatMap(RunsRegistry, (r) => r.create(payload)),
    )
    .handle('update', ({ params, payload }) =>
      Effect.flatMap(RunsRegistry, (r) => r.update(params.id, payload)).pipe(
        Effect.orDie,
      ),
    )
    .handle('checkpoints', ({ params }) =>
      Effect.flatMap(RunsRegistry, (r) => r.checkpoints(params.id)).pipe(
        Effect.map((c) => new Checkpoints(c)),
        Effect.orDie,
      ),
    ),
)

const CamerasLive = HttpApiBuilder.group(LabApi, 'Cameras', (handlers) =>
  handlers
    .handle('probe', () => Effect.flatMap(Cameras, (c) => c.probe()).pipe(Effect.orDie))
    .handle('previewStart', ({ payload }) =>
      Effect.flatMap(Cameras, (c) => c.previewStart(payload.indexes)).pipe(Effect.orDie),
    )
    .handle('previewStop', () =>
      Effect.flatMap(Cameras, (c) => c.previewStop()).pipe(Effect.orDie),
    )
    .handle('status', () => Effect.flatMap(Cameras, (c) => c.status()))
    .handle('confirm', ({ payload }) => Effect.flatMap(Cameras, (c) => c.confirm(payload))),
)

const robotState = Effect.gen(function* () {
  const driver = yield* DriverManager
  const r = yield* driver.robot()
  return new RobotState({
    state: r.state,
    backend: r.backend,
    source: r.source,
    leader: r.leader,
    joints: r.joints,
    rig: { followerPort: RIG.followerPort, leaderPort: RIG.leaderPort, robotId: RIG.robotId },
  })
})

const toDriverError = (e: Error) => new DriverError({ message: e.message })

const robotCmd = (cmd: string, extra: Record<string, unknown> = {}) =>
  Effect.gen(function* () {
    const driver = yield* DriverManager
    yield* driver.rpc(cmd, extra)
    return yield* robotState
  }).pipe(Effect.mapError(toDriverError))

const RobotLive = HttpApiBuilder.group(LabApi, 'Robot', (handlers) =>
  handlers
    .handle('state', () => robotState)
    .handle('connect', ({ payload }) =>
      Effect.gen(function* () {
        const driver = yield* DriverManager
        yield* driver.rpc('connect', {
          backend: payload.backend,
          followerPort: RIG.followerPort,
          leaderPort: payload.withLeader ? RIG.leaderPort : null,
          robotId: RIG.robotId,
        })
        yield* driver.setLeader(payload.backend === 'sim' ? true : payload.withLeader)
        return yield* robotState
      }).pipe(Effect.mapError(toDriverError)),
    )
    .handle('disconnect', () => robotCmd('disconnect'))
    .handle('torque', ({ payload }) => robotCmd('torque', { on: payload.on }))
    .handle('teleopStart', ({ payload }) => robotCmd('teleop_start', { source: payload.source }))
    .handle('teleopStop', () => robotCmd('teleop_stop'))
    .handle('teleopInput', ({ payload }) =>
      Effect.flatMap(DriverManager, (d) => d.rpc('teleop_input', { axes: payload.axes })).pipe(
        Effect.as({ ok: true }),
        Effect.mapError(toDriverError),
      ),
    )
    .handle('estop', () => robotCmd('estop')),
)

const RecordLive = HttpApiBuilder.group(LabApi, 'Record', (handlers) =>
  handlers
    .handle('status', () => Effect.flatMap(Recorder, (r) => r.status()))
    .handle('start', ({ payload }) => Effect.flatMap(Recorder, (r) => r.start(payload)))
    .handle('control', ({ payload }) => Effect.flatMap(Recorder, (r) => r.control(payload.action))),
)

const ServicesLayer = Layer.mergeAll(RunsRegistry.layer, Recorder.layer).pipe(
  Layer.provideMerge(Layer.mergeAll(DatasetCatalog.layer, Cameras.layer)),
  Layer.provideMerge(HfHub.layer),
  Layer.provideMerge(DriverManager.layer),
  Layer.provideMerge(FetchHttpClient.layer),
  Layer.provideMerge(NodeFileSystem.layer),
)

const GroupsLayer = Layer.mergeAll(
  HealthLive,
  HfLive,
  DatasetsLive,
  TrainingsLive,
  CamerasLive,
  RobotLive,
  RecordLive,
)

const PlatformLayer = Layer.mergeAll(Path.layer, Etag.layerWeak, HttpPlatform.layer).pipe(
  Layer.provideMerge(NodeFileSystem.layer),
)

const AppLayer = Layer.mergeAll(
  HttpApiBuilder.layer(LabApi, { openapiPath: '/api/openapi.json' }).pipe(
    Layer.provide(GroupsLayer),
  ),
  HttpApiScalar.layer(LabApi, { path: '/api/docs' }),
).pipe(Layer.provideMerge(ServicesLayer), Layer.provideMerge(PlatformLayer))

// Vite HMR must not rebuild the layer (and later: respawn the Python driver) on
// every reload — stash the handler on globalThis in dev.
const globalStore = globalThis as unknown as {
  __labApiHandler?: (request: Request) => Promise<Response>
}

export const apiHandler: (request: Request) => Promise<Response> = (globalStore.__labApiHandler ??=
  HttpRouter.toWebHandler(AppLayer).handler)
