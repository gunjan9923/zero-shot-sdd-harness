// API client + types for the Analyst Workspace.
// The app is served at basePath `/app`, but the FastAPI routes live at the
// origin root, so fetch paths are absolute-from-origin: `/datasets`, `/analyses`.

export type Schema = Record<string, string>
export type SampleRow = Record<string, unknown>

export interface Dataset {
  dataset_id: string
  name: string
  file_type: string
  row_count: number
  schema: Schema
  samples: SampleRow[]
  profile: unknown | null
}

export interface Analysis {
  analysis_id: string
  status: string
  answer: string | null
  plan: string | null
  code: string | null
  result: unknown
  retry_count: number
  chart_spec: unknown | null
  followups: unknown | null
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
