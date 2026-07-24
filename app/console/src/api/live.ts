import { NodeFileSystem } from '@effect/platform-node'
import { Effect, Layer, Path } from 'effect'
import { Etag, FetchHttpClient, HttpPlatform, HttpRouter } from 'effect/unstable/http'
import { HttpApiBuilder, HttpApiScalar } from 'effect/unstable/httpapi'
import { Checkpoints, HealthStatus, HfStatus, LabApi } from './contract'
import { DatasetCatalog } from './services/dataset-catalog'
import { HfHub } from './services/hf-hub'
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
      ),
    ),
)

const ServicesLayer = Layer.mergeAll(DatasetCatalog.layer, RunsRegistry.layer).pipe(
  Layer.provideMerge(HfHub.layer),
  Layer.provideMerge(FetchHttpClient.layer),
  Layer.provideMerge(NodeFileSystem.layer),
)

const GroupsLayer = Layer.mergeAll(HealthLive, HfLive, DatasetsLive, TrainingsLive)

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
