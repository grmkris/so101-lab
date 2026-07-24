import { queryOptions } from '@tanstack/react-query'
import { runApi } from './api'

export const healthQuery = queryOptions({
  queryKey: ['health'],
  queryFn: () => runApi((client) => client.Health.status()),
  refetchInterval: 30_000,
})
