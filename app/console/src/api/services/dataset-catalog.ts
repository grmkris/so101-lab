import * as os from 'node:os'
import { Context, Effect, FileSystem, Layer } from 'effect'
import { DatasetInfo } from '#/api/contract'
import { HfHub } from './hf-hub'

const LEROBOT_CACHE = `${os.homedir()}/.cache/huggingface/lerobot`

interface LocalMeta {
  readonly repoId: string
  readonly totalEpisodes: number | null
  readonly totalFrames: number | null
  readonly fps: number | null
  readonly cameras: ReadonlyArray<string>
  readonly codebaseVersion: string | null
}

export interface DatasetCatalogShape {
  readonly list: () => Effect.Effect<ReadonlyArray<DatasetInfo>>
}

export class DatasetCatalog extends Context.Service<DatasetCatalog, DatasetCatalogShape>()(
  'app/DatasetCatalog',
) {
  static readonly layer = Layer.effect(
    DatasetCatalog,
    Effect.gen(function* () {
      const fs = yield* FileSystem.FileSystem
      const hub = yield* HfHub

      const readMeta = (owner: string, name: string) =>
        fs.readFileString(`${LEROBOT_CACHE}/${owner}/${name}/meta/info.json`).pipe(
          Effect.map((raw): LocalMeta => {
            const info = JSON.parse(raw) as Record<string, unknown>
            const features = (info.features ?? {}) as Record<string, unknown>
            return {
              repoId: `${owner}/${name}`,
              totalEpisodes: (info.total_episodes as number) ?? null,
              totalFrames: (info.total_frames as number) ?? null,
              fps: (info.fps as number) ?? null,
              cameras: Object.keys(features)
                .filter((k) => k.startsWith('observation.images.'))
                .map((k) => k.replace('observation.images.', '')),
              codebaseVersion: (info.codebase_version as string) ?? null,
            }
          }),
          Effect.orElseSucceed(() => null),
        )

      const scanLocal = Effect.gen(function* () {
        const owners = yield* fs
          .readDirectory(LEROBOT_CACHE)
          .pipe(Effect.orElseSucceed(() => [] as Array<string>))
        const metas: Array<LocalMeta> = []
        for (const owner of owners) {
          if (owner === 'calibration' || owner.startsWith('.')) continue
          const names = yield* fs
            .readDirectory(`${LEROBOT_CACHE}/${owner}`)
            .pipe(Effect.orElseSucceed(() => [] as Array<string>))
          for (const name of names) {
            const meta = yield* readMeta(owner, name)
            if (meta) metas.push(meta)
          }
        }
        return metas
      })

      const loadSimSet = fs
        .readFileString(`${process.cwd()}/.data/sim-datasets.json`)
        .pipe(
          Effect.map((raw) => new Set(JSON.parse(raw) as Array<string>)),
          Effect.orElseSucceed(() => new Set<string>()),
        )

      return {
        list: () =>
          Effect.gen(function* () {
            const [local, hubRepos, simSet] = yield* Effect.all(
              [scanLocal, hub.listDatasets(), loadSimSet],
              { concurrency: 3 },
            )
            const hubById = new Map(hubRepos.map((r) => [r.id, r]))
            const localIds = new Set(local.map((m) => m.repoId))

            const merged = local.map(
              (m) =>
                new DatasetInfo({
                  ...m,
                  isLocal: true,
                  onHub: hubById.has(m.repoId),
                  hubLastModified: hubById.get(m.repoId)?.lastModified ?? null,
                  sim: simSet.has(m.repoId),
                }),
            )
            for (const r of hubRepos) {
              if (localIds.has(r.id)) continue
              merged.push(
                new DatasetInfo({
                  repoId: r.id,
                  isLocal: false,
                  onHub: true,
                  totalEpisodes: null,
                  totalFrames: null,
                  fps: null,
                  cameras: [],
                  codebaseVersion: null,
                  hubLastModified: r.lastModified,
                  sim: simSet.has(r.id),
                }),
              )
            }
            return merged.sort((a, b) =>
              (b.hubLastModified ?? '').localeCompare(a.hubLastModified ?? ''),
            )
          }),
      }
    }),
  )
}
