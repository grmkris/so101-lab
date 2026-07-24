import { Effect } from 'effect'
import { FetchHttpClient } from 'effect/unstable/http'
import { HttpApiClient } from 'effect/unstable/httpapi'
import { LabApi } from '#/api/contract'

const baseUrl =
  typeof window === 'undefined' ? 'http://localhost:3000' : window.location.origin

const clientEffect = HttpApiClient.make(LabApi, { baseUrl })

type LabClient = Effect.Success<typeof clientEffect>

/** Narrow promise bridge for TanStack Query — components never touch Effect. */
export const runApi = <A, E>(use: (client: LabClient) => Effect.Effect<A, E>): Promise<A> =>
  Effect.flatMap(clientEffect, use).pipe(
    Effect.provide(FetchHttpClient.layer),
    Effect.runPromise,
  )
