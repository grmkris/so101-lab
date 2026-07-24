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
    sim: Schema.Boolean,
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

export class ProbedCamera extends Schema.Class<ProbedCamera>('ProbedCamera')(
  Schema.Struct({
    index: Schema.Number,
    width: Schema.Number,
    height: Schema.Number,
  }),
) {}

export class CameraMapping extends Schema.Class<CameraMapping>('CameraMapping')(
  Schema.Struct({
    workspace: Schema.NullOr(Schema.Number),
    wrist: Schema.NullOr(Schema.Number),
  }),
) {}

export class CameraStatus extends Schema.Class<CameraStatus>('CameraStatus')(
  Schema.Struct({
    previewing: Schema.Array(Schema.String),
    brightness: Schema.Record(Schema.String, Schema.Number),
    mapping: CameraMapping,
    brightnessBand: Schema.Struct({ min: Schema.Number, max: Schema.Number }),
  }),
) {}

export const CamerasGroup = HttpApiGroup.make('Cameras').add(
  HttpApiEndpoint.get('probe', '/cameras/probe', { success: Schema.Array(ProbedCamera) }),
  HttpApiEndpoint.post('previewStart', '/cameras/preview/start', {
    payload: Schema.Struct({ indexes: Schema.Array(Schema.Number) }),
    success: Schema.Struct({ started: Schema.Array(Schema.String) }),
  }),
  HttpApiEndpoint.post('previewStop', '/cameras/preview/stop', {
    success: Schema.Struct({ stopped: Schema.Boolean }),
  }),
  HttpApiEndpoint.get('status', '/cameras/status', { success: CameraStatus }),
  HttpApiEndpoint.post('confirm', '/cameras/confirm', {
    payload: CameraMapping,
    success: CameraMapping,
  }),
)

/** Driver/hardware failure surfaced with its actionable message (port busy hints etc). */
export class DriverError extends Schema.TaggedErrorClass<DriverError>()('DriverError', {
  message: Schema.String,
}) {}

export class RobotState extends Schema.Class<RobotState>('RobotState')(
  Schema.Struct({
    state: Schema.String, // disconnected | connected | teleop | recording
    backend: Schema.String, // real | sim
    leader: Schema.Boolean,
    joints: Schema.Record(Schema.String, Schema.Number),
    rig: Schema.Struct({
      followerPort: Schema.String,
      leaderPort: Schema.String,
      robotId: Schema.String,
    }),
  }),
) {}

export const RobotGroup = HttpApiGroup.make('Robot').add(
  HttpApiEndpoint.get('state', '/robot/state', { success: RobotState }),
  HttpApiEndpoint.post('connect', '/robot/connect', {
    payload: Schema.Struct({ withLeader: Schema.Boolean, backend: Schema.String }),
    success: RobotState,
    error: DriverError,
  }),
  HttpApiEndpoint.post('disconnect', '/robot/disconnect', {
    success: RobotState,
    error: DriverError,
  }),
  HttpApiEndpoint.post('torque', '/robot/torque', {
    payload: Schema.Struct({ on: Schema.Boolean }),
    success: RobotState,
    error: DriverError,
  }),
  HttpApiEndpoint.post('teleopStart', '/robot/teleop/start', {
    success: RobotState,
    error: DriverError,
  }),
  HttpApiEndpoint.post('teleopStop', '/robot/teleop/stop', {
    success: RobotState,
    error: DriverError,
  }),
  HttpApiEndpoint.post('estop', '/robot/estop', { success: RobotState, error: DriverError }),
)

const runId = { id: Schema.String }

export const TrainingsGroup = HttpApiGroup.make('Trainings').add(
  HttpApiEndpoint.get('list', '/runs', { success: Schema.Array(RunInfo) }),
  HttpApiEndpoint.get('get', '/runs/:id', { params: runId, success: RunInfo }),
  HttpApiEndpoint.post('create', '/runs', { payload: RunCreate, success: RunInfo }),
  HttpApiEndpoint.patch('update', '/runs/:id', { params: runId, payload: RunPatch, success: RunInfo }),
  HttpApiEndpoint.get('checkpoints', '/runs/:id/checkpoints', { params: runId, success: Checkpoints }),
)

export class RecordStatus extends Schema.Class<RecordStatus>('RecordStatus')(
  Schema.Struct({
    active: Schema.Boolean,
    phase: Schema.String, // idle | recording | resetting | done | failed
    episode: Schema.Number,
    saved: Schema.Number,
    total: Schema.Number,
    repoId: Schema.NullOr(Schema.String),
  }),
) {}

export const RecordGroup = HttpApiGroup.make('Record').add(
  HttpApiEndpoint.get('status', '/record/status', { success: RecordStatus }),
  HttpApiEndpoint.post('start', '/record/start', {
    payload: Schema.Struct({
      repoName: Schema.String,
      task: Schema.String,
      numEpisodes: Schema.Number,
      episodeS: Schema.Number,
      resetS: Schema.Number,
      resume: Schema.Boolean,
    }),
    success: RecordStatus,
    error: DriverError,
  }),
  HttpApiEndpoint.post('control', '/record/control', {
    payload: Schema.Struct({ action: Schema.String }), // keep | rerecord | finish
    success: RecordStatus,
    error: DriverError,
  }),
)

export const LabApi = HttpApi.make('LabConsole')
  .add(HealthGroup)
  .add(HfGroup)
  .add(DatasetsGroup)
  .add(TrainingsGroup)
  .add(CamerasGroup)
  .add(RobotGroup)
  .add(RecordGroup)
  .prefix('/api')
