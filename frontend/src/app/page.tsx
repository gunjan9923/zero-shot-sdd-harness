'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  deleteDataset,
  fetchDailyCost,
  fetchProfile,
  listDatasets,
  listHistory,
  runAnalysisStream,
  uploadDataset,
  type Analysis,
  type DailyCost,
  type Dataset,
  type DatasetListItem,
  type HistoryItem,
} from '@/lib/api'
import { Upload } from '@/components/Upload'
import { QuestionInput } from '@/components/QuestionInput'
import { Answer } from '@/components/Answer'
import { Profile } from '@/components/Profile'
import { Chart } from '@/components/Chart'
import { Followups } from '@/components/Followups'
import { Steps } from '@/components/Steps'
import { CostMeter } from '@/components/CostMeter'
import { Library } from '@/components/Library'
import { History } from '@/components/History'

export default function Home() {
  const [datasets, setDatasets] = useState<DatasetListItem[]>([])
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [includedIds, setIncludedIds] = useState<string[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const [question, setQuestion] = useState('')
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [asking, setAsking] = useState(false)
  const [steps, setSteps] = useState<string[]>([])
  const [analysisError, setAnalysisError] = useState<string | null>(null)

  const [daily, setDaily] = useState<DailyCost | null>(null)
  const [historyItems, setHistoryItems] = useState<HistoryItem[] | null>(null)

  const addFileRef = useRef<HTMLInputElement>(null)

  const refreshLibrary = useCallback(async () => {
    try {
      setDatasets(await listDatasets())
    } catch {
      /* library is best-effort */
    }
  }, [])

  const refreshDaily = useCallback(async () => {
    try {
      setDaily(await fetchDailyCost())
    } catch {
      /* cost meter is best-effort */
    }
  }, [])

  useEffect(() => {
    refreshLibrary()
    refreshDaily()
  }, [refreshLibrary, refreshDaily])

  async function handleUpload(file: File, setAsPrimary = true) {
    setUploading(true)
    setUploadError(null)
    try {
      const ds = await uploadDataset(file)
      await refreshLibrary()
      if (setAsPrimary) {
        setDataset(ds)
        setIncludedIds([])
        setAnalysis(null)
        setAnalysisError(null)
        setHistoryItems(null)
      } else {
        // "Add another file" → auto-include it in the next (multi-file) question.
        setIncludedIds(prev => (prev.includes(ds.dataset_id) ? prev : [...prev, ds.dataset_id]))
      }
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  // Load a library dataset as the primary one (fetch its profile for the panel).
  async function selectDataset(id: string) {
    const item = datasets.find(d => d.dataset_id === id)
    if (!item) return
    let profile = null
    try {
      profile = await fetchProfile(id)
    } catch {
      /* profile is best-effort */
    }
    setDataset({
      dataset_id: item.dataset_id,
      name: item.name,
      file_type: item.file_type,
      row_count: item.row_count,
      schema: {},
      samples: [],
      profile,
    })
    setIncludedIds(prev => prev.filter(x => x !== id))
    setAnalysis(null)
    setAnalysisError(null)
    setHistoryItems(null)
  }

  function toggleInclude(id: string) {
    setIncludedIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  async function handleDelete(id: string) {
    try {
      await deleteDataset(id)
    } catch {
      /* ignore — refresh will reflect reality */
    }
    setIncludedIds(prev => prev.filter(x => x !== id))
    if (dataset?.dataset_id === id) {
      setDataset(null)
      setAnalysis(null)
    }
    await refreshLibrary()
  }

  async function ask(q: string) {
    const trimmed = q.trim()
    if (!dataset || !trimmed) return
    setQuestion(trimmed)
    setAsking(true)
    setAnalysisError(null)
    setAnalysis(null)
    setSteps([])
    const datasetIds = [dataset.dataset_id, ...includedIds]
    try {
      const result = await runAnalysisStream(datasetIds, trimmed, step =>
        setSteps(prev => [...prev, step])
      )
      setAnalysis(result)
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.analysis) setAnalysis(err.analysis)
        else setAnalysisError(err.message)
      } else {
        setAnalysisError('Something went wrong running the analysis.')
      }
    } finally {
      setAsking(false)
      refreshDaily()
    }
  }

  async function openHistory() {
    if (!dataset) return
    try {
      setHistoryItems(await listHistory(dataset.dataset_id))
    } catch {
      setHistoryItems([])
    }
  }

  const multiCount = 1 + includedIds.length

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-gray-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold tracking-tight text-gray-900">
              Analyst Workspace
            </span>
            <span className="hidden text-xs text-gray-400 sm:inline">
              local CSV / Excel analysis
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <CostMeter analysis={analysis} daily={daily} />
            <button
              type="button"
              onClick={openHistory}
              disabled={!dataset}
              className="rounded-md border border-gray-200 bg-white px-2.5 py-1 text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              History
            </button>
            <button
              type="button"
              onClick={() => addFileRef.current?.click()}
              title="Upload another file to join/compare with the current one"
              className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2.5 py-1 text-gray-600 hover:bg-gray-50"
            >
              + Add another file
            </button>
            <input
              ref={addFileRef}
              type="file"
              accept=".csv,.xlsx"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0]
                if (f) handleUpload(f, false)
                e.target.value = ''
              }}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-4 py-6 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-4">
          <Library
            datasets={datasets}
            activeId={dataset?.dataset_id ?? null}
            includedIds={includedIds}
            onSelect={selectDataset}
            onToggleInclude={toggleInclude}
            onDelete={handleDelete}
          />
        </aside>

        <section className="space-y-6">
          <Upload
            dataset={dataset}
            uploading={uploading}
            error={uploadError}
            onUpload={handleUpload}
          />

          {dataset && <Profile profile={dataset.profile} rowCount={dataset.row_count} />}

          {multiCount > 1 && (
            <p className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700">
              Multi-file query: this question will run across {multiCount} datasets
              (primary + {includedIds.length} joined). Ask something that combines them.
            </p>
          )}

          <QuestionInput
            value={question}
            onChange={setQuestion}
            onAsk={() => ask(question)}
            noDataset={!dataset}
            loading={asking}
          />

          {asking && <Steps steps={steps} />}

          {!asking && analysisError && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              {analysisError}
            </div>
          )}

          {!asking && analysis && <Answer analysis={analysis} />}
          {!asking && analysis && <Chart spec={analysis.chart_spec} />}
          {!asking && analysis && (
            <Followups followups={analysis.followups} onPick={ask} disabled={asking} />
          )}

          {historyItems && (
            <History items={historyItems} onClose={() => setHistoryItems(null)} />
          )}

          {!asking && !analysis && !analysisError && (
            <p className="rounded-lg border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-400">
              {dataset
                ? 'Ask a question to get a plain-language answer plus the exact code that ran.'
                : 'Upload a dataset, then ask a question.'}
            </p>
          )}
        </section>
      </main>
    </div>
  )
}
