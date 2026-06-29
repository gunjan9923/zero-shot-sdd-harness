// API client + types for the Analyst Workspace.
// The app is served at basePath `/app`, but the FastAPI routes live at the
// origin root, so fetch paths are absolute-from-origin: `/datasets`, `/analyses`.

export type Schema = Record<string, string>
export type SampleRow = Record<string, unknown>

/** Per-column auto-profile (Phase 2). Numeric columns carry min/max/mean;
 *  categorical columns carry `top` value counts. `missing` is always present. */
export interface ColumnProfile {
  type?: string
  missing?: number
  min?: number | string | null
  max?: number | string | null
  mean?: number | string | null
  top?: Array<{ value: unknown; count: number }> | Record<string, number> | null
}

export type DatasetProfile = Record<string, ColumnProfile>

/** A Vega-Lite spec object returned with an analysis (Phase 2). */
export type ChartSpec = Record<string, unknown>

export interface Dataset {
  dataset_id: string
  name: string
  file_type: string
  row_count: number
  schema: Schema
  samples: SampleRow[]
  profile: DatasetProfile | null
}

export interface Analysis {
  analysis_id: string
  status: string
  answer: string | null
  plan: string | null
  code: string | null
  result: unknown
  retry_count: number
  chart_spec: ChartSpec | null
  followups: string[] | null
  tokens: number | null
  estimated_cost_usd: number | null
  error: string | null
}

/** Raised when the API responds with a non-2xx status carrying a detail payload. */
export class ApiError extends Error {
  status: number
  /** Optional analysis body returned alongside a 422 failed analysis. */
  analysis?: Analysis

  constructor(message: string, status: number, analysis?: Analysis) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.analysis = analysis
  }
}

const NETWORK_ERROR = 'Network error — is the server running?'

async function parseJson(res: Response): Promise<Record<string, unknown>> {
  try {
    return (await res.json()) as Record<string, unknown>
  } catch {
    return {}
  }
}

function detailMessage(body: Record<string, unknown>, status: number): string {
  const detail = body.detail as { message?: string; code?: string } | string | undefined
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object' && detail.message) return detail.message
  return `Request failed (${status})`
}

/** Upload a CSV/Excel file. POST /datasets (multipart, field name `file`). */
export async function uploadDataset(file: File): Promise<Dataset> {
  const form = new FormData()
  form.append('file', file)

  let res: Response
  try {
    res = await fetch('/datasets', { method: 'POST', body: form })
  } catch {
    throw new ApiError(NETWORK_ERROR, 0)
  }

  const body = await parseJson(res)
  if (!res.ok) {
    throw new ApiError(detailMessage(body, res.status), res.status)
  }
  return (body.data as Dataset)
}

/** Fetch a dataset's auto-profile. GET /datasets/{id}/profile (Phase 2).
 *  Used when the upload response did not already embed the profile inline. */
export async function fetchProfile(datasetId: string): Promise<DatasetProfile | null> {
  let res: Response
  try {
    res = await fetch(`/datasets/${encodeURIComponent(datasetId)}/profile`)
  } catch {
    throw new ApiError(NETWORK_ERROR, 0)
  }

  const body = await parseJson(res)
  if (!res.ok) {
    throw new ApiError(detailMessage(body, res.status), res.status)
  }
  const data = body.data as { profile?: DatasetProfile | null } | undefined
  return data?.profile ?? null
}

/** Ask a question about a dataset. POST /analyses (JSON). */
export async function runAnalysis(datasetId: string, question: string): Promise<Analysis> {
  let res: Response
  try {
    res = await fetch('/analyses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: datasetId, question }),
    })
  } catch {
    throw new ApiError(NETWORK_ERROR, 0)
  }

  const body = await parseJson(res)

  // A 422 means the agent exhausted retries; the failed analysis (with the last
  // code it tried) is returned so we can still "show what it tried".
  if (res.status === 422) {
    const data = body.data as Analysis | undefined
    const message = data?.error || detailMessage(body, res.status)
    throw new ApiError(message, res.status, data)
  }

  if (!res.ok) {
    throw new ApiError(detailMessage(body, res.status), res.status)
  }
  return body.data as Analysis
}

// --- Phase 3: library, history, cost, streaming ----------------------------

export interface DatasetListItem {
  dataset_id: string
  name: string
  file_type: string
  row_count: number
  created_at: string | null
}

/** List persisted datasets for the library sidebar. GET /datasets */
export async function listDatasets(): Promise<DatasetListItem[]> {
  const res = await fetch('/datasets').catch(() => {
    throw new ApiError(NETWORK_ERROR, 0)
  })
  const body = await parseJson(res)
  if (!res.ok) throw new ApiError(detailMessage(body, res.status), res.status)
  const data = body.data as { datasets?: DatasetListItem[] } | undefined
  return data?.datasets ?? []
}

/** Delete a dataset and its file. DELETE /datasets/{id} */
export async function deleteDataset(datasetId: string): Promise<void> {
  const res = await fetch(`/datasets/${encodeURIComponent(datasetId)}`, {
    method: 'DELETE',
  }).catch(() => {
    throw new ApiError(NETWORK_ERROR, 0)
  })
  if (!res.ok) {
    const body = await parseJson(res)
    throw new ApiError(detailMessage(body, res.status), res.status)
  }
}

export interface DailyCost {
  date: string
  total_tokens: number
  total_cost_usd: number
}

/** Running daily total of tokens + cost. GET /cost/daily */
export async function fetchDailyCost(): Promise<DailyCost> {
  const res = await fetch('/cost/daily').catch(() => {
    throw new ApiError(NETWORK_ERROR, 0)
  })
  const body = await parseJson(res)
  if (!res.ok) throw new ApiError(detailMessage(body, res.status), res.status)
  return body.data as DailyCost
}

export interface HistoryItem {
  analysis_id: string
  dataset_id: string
  question: string
  code: string | null
  answer: string | null
  status: string
  created_at: string | null
  completed_at: string | null
  estimated_cost_usd: number | null
}

/** Past analyses for the audit-trail history view. GET /analyses?dataset_id= */
export async function listHistory(datasetId?: string): Promise<HistoryItem[]> {
  const url = datasetId
    ? `/analyses?dataset_id=${encodeURIComponent(datasetId)}`
    : '/analyses'
  const res = await fetch(url).catch(() => {
    throw new ApiError(NETWORK_ERROR, 0)
  })
  const body = await parseJson(res)
  if (!res.ok) throw new ApiError(detailMessage(body, res.status), res.status)
  const data = body.data as { analyses?: HistoryItem[] } | undefined
  return data?.analyses ?? []
}

/** Fetch a single analysis by id. GET /analyses/{id} */
export async function getAnalysis(analysisId: string): Promise<Analysis> {
  const res = await fetch(`/analyses/${encodeURIComponent(analysisId)}`).catch(() => {
    throw new ApiError(NETWORK_ERROR, 0)
  })
  const body = await parseJson(res)
  if (!res.ok) throw new ApiError(detailMessage(body, res.status), res.status)
  return body.data as Analysis
}

/**
 * Run an analysis with live progress via SSE. POST /analyses/stream.
 * Calls `onStep` for each progress event, then resolves with the full Analysis
 * (fetched on the terminal `done` event). One or more `dataset_ids` enables
 * multi-file analysis. Falls back to the blocking endpoint on stream failure.
 */
export async function runAnalysisStream(
  datasetIds: string[],
  question: string,
  onStep: (step: string) => void
): Promise<Analysis> {
  let res: Response
  try {
    res = await fetch('/analyses/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_id: datasetIds[0],
        question,
        dataset_ids: datasetIds,
      }),
    })
  } catch {
    // Network/stream unavailable → fall back to the blocking path.
    return runAnalysis(datasetIds[0], question)
  }

  if (!res.ok || !res.body) {
    return runAnalysis(datasetIds[0], question)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let analysisId: string | null = null
  let failed: { id: string } | null = null

  // Read the SSE stream line-by-line; events are `data: {json}\n\n`.
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''
    for (const chunk of chunks) {
      const line = chunk.split('\n').find(l => l.startsWith('data:'))
      if (!line) continue
      let evt: { step?: string; analysis_id?: string; status?: string }
      try {
        evt = JSON.parse(line.slice(5).trim())
      } catch {
        continue
      }
      if (evt.step && evt.step !== 'done') onStep(evt.step)
      if (evt.step === 'done' && evt.analysis_id) {
        analysisId = evt.analysis_id
        if (evt.status === 'failed') failed = { id: evt.analysis_id }
      }
    }
  }

  if (!analysisId) return runAnalysis(datasetIds[0], question)

  const analysis = await getAnalysis(analysisId)
  if (failed) {
    throw new ApiError(analysis.error || 'The agent could not produce a valid answer.', 422, analysis)
  }
  return analysis
}
