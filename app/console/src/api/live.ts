import { Effect, FileSystem, Layer, Path } from 'effect'
import { Etag, HttpPlatform, HttpRouter } from 'effect/unstable/http'
import { HttpApiBuilder, HttpApiScalar } from 'effect/unstable/httpapi'
import { HealthStatus, LabApi } from './contract'

const HealthLive = HttpApiBuilder.group(LabApi, 'Health', (handlers) =>
  handlers.handle('status', () =>
    Effect.succeed(new HealthStatus({ ok: true, hfUser: 'kris0', version: '0.1.0' })),
  ),
)

const PlatformLayer = Layer.mergeAll(Path.layer, Etag.layerWeak, HttpPlatform.layer).pipe(
  Layer.provideMerge(FileSystem.layerNoop({})),
)

const AppLayer = Layer.mergeAll(
  HttpApiBuilder.layer(LabApi, { openapiPath: '/api/openapi.json' }).pipe(
    Layer.provide(HealthLive),
  ),
  HttpApiScalar.layer(LabApi, { path: '/api/docs' }),
).pipe(Layer.provideMerge(PlatformLayer))

// Vite HMR must not rebuild the layer (and later: respawn the Python driver) on
// every reload — stash the handler on globalThis in dev.
const globalStore = globalThis as unknown as {
  __labApiHandler?: (request: Request) => Promise<Response>
}

export const apiHandler: (request: Request) => Promise<Response> = (globalStore.__labApiHandler ??=
  HttpRouter.toWebHandler(AppLayer).handler)
