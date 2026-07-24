import { Schema } from 'effect'
import { HttpApi, HttpApiEndpoint, HttpApiGroup } from 'effect/unstable/httpapi'

export class HealthStatus extends Schema.Class<HealthStatus>('HealthStatus')(
  Schema.Struct({
    ok: Schema.Boolean,
    hfUser: Schema.String,
    version: Schema.String,
  }),
) {}

export const HealthGroup = HttpApiGroup.make('Health').add(
  HttpApiEndpoint.get('status', '/health', { success: HealthStatus }),
)

export const LabApi = HttpApi.make('LabConsole').add(HealthGroup).prefix('/api')
