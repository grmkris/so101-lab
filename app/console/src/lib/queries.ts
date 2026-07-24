import { queryOptions } from '@tanstack/react-query'
import type { RunCreate, RunPatch } from '#/api/contract'
import { runApi } from './api'

export const healthQuery = queryOptions({
  queryKey: ['health'],
  queryFn: () => runApi((client) => client.Health.status()),
  refetchInterval: 30_000,
})

export const hfStatusQuery = queryOptions({
  queryKey: ['hf-status'],
  queryFn: () => runApi((client) => client.Hf.status()),
  staleTime: 5 * 60_000,
})

export const datasetsQuery = queryOptions({
  queryKey: ['datasets'],
  queryFn: () => runApi((client) => client.Datasets.list()),
})

export const runsQuery = queryOptions({
  queryKey: ['runs'],
  queryFn: () => runApi((client) => client.Trainings.list()),
})

export const runQuery = (id: string) =>
  queryOptions({
    queryKey: ['runs', id],
    queryFn: () => runApi((client) => client.Trainings.get({ params: { id } })),
  })

export const checkpointsQuery = (id: string) =>
  queryOptions({
    queryKey: ['runs', id, 'checkpoints'],
    queryFn: () => runApi((client) => client.Trainings.checkpoints({ params: { id } })),
    refetchInterval: 60_000,
  })

export const createRun = (payload: typeof RunCreate.Type) =>
  runApi((client) => client.Trainings.create({ payload }))

export const patchRun = (id: string, payload: typeof RunPatch.Type) =>
  runApi((client) => client.Trainings.update({ params: { id }, payload }))
