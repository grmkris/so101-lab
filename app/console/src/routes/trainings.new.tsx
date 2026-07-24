import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { createRun, datasetsQuery } from '#/lib/queries'

type NewTrainingSearch = { dataset?: string }

export const Route = createFileRoute('/trainings/new')({
  component: NewTrainingPage,
  validateSearch: (search: Record<string, unknown>): NewTrainingSearch => ({
    dataset: typeof search.dataset === 'string' ? search.dataset : undefined,
  }),
})

function NewTrainingPage() {
  const { dataset } = Route.useSearch()
  const datasets = useQuery(datasetsQuery)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [datasetRepoId, setDatasetRepoId] = useState(dataset ?? '')
  const [episodes, setEpisodes] = useState('')
  const [pretrainedPath, setPretrainedPath] = useState('')
  const [steps, setSteps] = useState(40000)
  const [batchSize, setBatchSize] = useState(16)
  const [saveFreq, setSaveFreq] = useState(5000)
  const [hypothesis, setHypothesis] = useState('')

  const create = useMutation({
    mutationFn: () =>
      createRun({
        name,
        datasetRepoId,
        episodes: episodes.trim() === '' ? null : episodes.trim(),
        pretrainedPath: pretrainedPath.trim() === '' ? null : pretrainedPath.trim(),
        steps,
        batchSize,
        saveFreq,
        hypothesis: hypothesis.trim() === '' ? null : hypothesis.trim(),
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      navigate({ to: '/trainings/$runId', params: { runId: run.id } })
    },
  })

  const field = 'mt-1 w-full rounded border bg-transparent px-2 py-1.5 text-sm'
  const label = 'mt-4 block text-sm font-medium'

  return (
    <div className="max-w-xl p-6">
      <h1 className="text-2xl font-bold">New training</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Generates a version-matched Colab cell (lerobot v0.6.0, checkpoints pushed to Hub)
      </p>

      <label className={label}>
        Dataset
        <select
          className={field}
          value={datasetRepoId}
          onChange={(e) => setDatasetRepoId(e.target.value)}
        >
          <option value="">select…</option>
          {(datasets.data ?? [])
            .filter((d) => d.onHub)
            .map((d) => (
              <option key={d.repoId} value={d.repoId}>
                {d.repoId} {d.totalEpisodes ? `(${d.totalEpisodes} eps)` : ''}
              </option>
            ))}
        </select>
      </label>

      <label className={label}>
        Model name (kris0/…)
        <input
          className={field}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="act_wall_v4"
        />
      </label>

      <label className={label}>
        Hypothesis (what will this run prove?)
        <input
          className={field}
          value={hypothesis}
          onChange={(e) => setHypothesis(e.target.value)}
          placeholder="40k steps closes the ±45° gap at edges"
        />
      </label>

      <label className={label}>
        Episodes include-list (optional, e.g. [0,1,…,56])
        <input
          className={field}
          value={episodes}
          onChange={(e) => setEpisodes(e.target.value)}
          placeholder="leave empty for all episodes"
        />
      </label>

      <label className={label}>
        Continue from checkpoint (optional pretrained path)
        <input
          className={field}
          value={pretrainedPath}
          onChange={(e) => setPretrainedPath(e.target.value)}
          placeholder="leave empty to train from scratch (default at our scale)"
        />
      </label>

      <div className="flex gap-4">
        <label className={label}>
          Steps
          <input
            type="number"
            className={field}
            value={steps}
            onChange={(e) => setSteps(Number(e.target.value))}
          />
        </label>
        <label className={label}>
          Batch
          <input
            type="number"
            className={field}
            value={batchSize}
            onChange={(e) => setBatchSize(Number(e.target.value))}
          />
        </label>
        <label className={label}>
          Save every
          <input
            type="number"
            className={field}
            value={saveFreq}
            onChange={(e) => setSaveFreq(Number(e.target.value))}
          />
        </label>
      </div>

      <button
        type="button"
        disabled={!name || !datasetRepoId || create.isPending}
        onClick={() => create.mutate()}
        className="mt-6 rounded bg-foreground px-4 py-2 text-sm text-background disabled:opacity-50"
      >
        {create.isPending ? 'creating…' : 'Create run'}
      </button>
      {create.isError && <p className="mt-2 text-sm text-red-500">{String(create.error)}</p>}
    </div>
  )
}
