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

export class HfStatus extends Schema.Class<HfStatus>('HfStatus')(
  Schema.Struct({
    authenticated: Schema.Boolean,
    user: Schema.NullOr(Schema.String),
  }),
) {}

export const HfGroup = HttpApiGroup.make('Hf').add(
  HttpApiEndpoint.get('status', '/hf/status', { success: HfStatus }),
)

export class DatasetInfo extends Schema.Class<DatasetInfo>('DatasetInfo')(
  Schema.Struct({
    repoId: Schema.String,
    isLocal: Schema.Boolean,
    onHub: Schema.Boolean,
    totalEpisodes: Schema.NullOr(Schema.Number),
    totalFrames: Schema.NullOr(Schema.Number),
    fps: Schema.NullOr(Schema.Number),
    cameras: Schema.Array(Schema.String),
    codebaseVersion: Schema.NullOr(Schema.String),
    hubLastModified: Schema.NullOr(Schema.String),
  }),
) {}

export const DatasetsGroup = HttpApiGroup.make('Datasets').add(
  HttpApiEndpoint.get('list', '/datasets', { success: Schema.Array(DatasetInfo) }),
)

export class RunConfig extends Schema.Class<RunConfig>('RunConfig')(
  Schema.Struct({
    datasetRepoId: Schema.String,
    episodes: Schema.NullOr(Schema.String),
    policyType: Schema.String,
    pretrainedPath: Schema.NullOr(Schema.String),
    steps: Schema.Number,
    batchSize: Schema.Number,
    saveFreq: Schema.Number,
  }),
) {}

export class RunInfo extends Schema.Class<RunInfo>('RunInfo')(
  Schema.Struct({
    id: Schema.String,
    name: Schema.String,
    status: Schema.String, // draft | launched | imported (derived states come later)
    hubModelId: Schema.String,
    createdAt: Schema.NullOr(Schema.String),
    hypothesis: Schema.NullOr(Schema.String),
    finding: Schema.NullOr(Schema.String),
    config: Schema.NullOr(RunConfig),
    colabCell: Schema.NullOr(Schema.String),
  }),
) {}

export class RunCreate extends Schema.Class<RunCreate>('RunCreate')(
  Schema.Struct({
    name: Schema.String,
    datasetRepoId: Schema.String,
    episodes: Schema.NullOr(Schema.String),
    pretrainedPath: Schema.NullOr(Schema.String),
    steps: Schema.Number,
    batchSize: Schema.Number,
    saveFreq: Schema.Number,
    hypothesis: Schema.NullOr(Schema.String),
  }),
) {}

export class RunPatch extends Schema.Class<RunPatch>('RunPatch')(
  Schema.Struct({
    status: Schema.NullOr(Schema.String),
    hypothesis: Schema.NullOr(Schema.String),
    finding: Schema.NullOr(Schema.String),
  }),
) {}

export class Checkpoints extends Schema.Class<Checkpoints>('Checkpoints')(
  Schema.Struct({
    hubModelId: Schema.String,
    steps: Schema.Array(Schema.String),
  }),
) {}

const runId = { id: Schema.String }

export const TrainingsGroup = HttpApiGroup.make('Trainings').add(
  HttpApiEndpoint.get('list', '/runs', { success: Schema.Array(RunInfo) }),
  HttpApiEndpoint.get('get', '/runs/:id', { params: runId, success: RunInfo }),
  HttpApiEndpoint.post('create', '/runs', { payload: RunCreate, success: RunInfo }),
  HttpApiEndpoint.patch('update', '/runs/:id', { params: runId, payload: RunPatch, success: RunInfo }),
  HttpApiEndpoint.get('checkpoints', '/runs/:id/checkpoints', { params: runId, success: Checkpoints }),
)

export const LabApi = HttpApi.make('LabConsole')
  .add(HealthGroup)
  .add(HfGroup)
  .add(DatasetsGroup)
  .add(TrainingsGroup)
  .prefix('/api')
