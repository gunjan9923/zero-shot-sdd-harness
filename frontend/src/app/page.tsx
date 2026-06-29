'use client'

import { useState } from 'react'
import { ApiError, runAnalysis, uploadDataset, type Analysis, type Dataset } from '@/lib/api'
import { Upload } from '@/components/Upload'
import { QuestionInput } from '@/components/QuestionInput'
import { Answer } from '@/components/Answer'
import { Working } from '@/components/Working'
import { StubPanel, ComingSoonPill } from '@/components/Stub'

export default function Home() {
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const [question, setQuestion] = useState('')
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [asking, setAsking] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)

  async function handleUpload(file: File) {
    setUploading(true)
    setUploadError(null)
    try {
      const ds = await uploadDataset(file)
      setDataset(ds)
      // A new dataset invalidates any prior answer.
      setAnalysis(null)
      setAnalysisError(null)
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  async function handleAsk() {
    if (!dataset || !question.trim()) return
    setAsking(true)
    setAnalysisError(null)
    setAnalysis(null)
    try {
      const result = await runAnalysis(dataset.dataset_id, question.trim())
      setAnalysis(result)
    } catch (err) {
      if (err instanceof ApiError) {
        // A 422 carries the failed analysis (with the last code) — render it so
        // the user can see what the agent tried.
        if (err.analysis) {
          setAnalysis(err.analysis)
        } else {
          setAnalysisError(err.message)
        }
      } else {
        setAnalysisError('Something went wrong running the analysis.')
      }
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="min-h-screen">
      {/* Top bar */}
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
          <div className="flex items-center gap-3 text-xs text-gray-400">
            <span className="inline-flex items-center gap-1.5">
              Cost: — <ComingSoonPill />
            </span>
            <span className="inline-flex items-center gap-1.5">
              History <ComingSoonPill />
            </span>
            <button
              type="button"
              disabled
              title="Coming soon — multi-file analysis"
              className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1 text-gray-400"
            >
              + Add another file <ComingSoonPill />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-4 py-6 lg:grid-cols-[260px_1fr]">
        {/* Left sidebar — Dataset library (stub) */}
        <aside className="space-y-4">
          <StubPanel
            title="Dataset library"
            hint="Your uploaded datasets will be saved here and reloadable across sessions."
          />
        </aside>

        {/* Main column — the conversation */}
        <section className="space-y-6">
          <Upload
            dataset={dataset}
            uploading={uploading}
            error={uploadError}
            onUpload={handleUpload}
          />

          {/* Profile (stub) */}
          <StubPanel
            title="Profile"
            hint="Auto-detected columns, types, ranges, and missing-value counts."
          />

          <QuestionInput
            value={question}
            onChange={setQuestion}
            onAsk={handleAsk}
            noDataset={!dataset}
            loading={asking}
          />

          {/* Answer / loading / error */}
          {asking && <Working />}

          {!asking && analysisError && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              {analysisError}
            </div>
          )}

          {!asking && analysis && <Answer analysis={analysis} />}

          {!asking && !analysis && !analysisError && (
            <p className="rounded-lg border border-dashed border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-400">
              {dataset
                ? 'Ask a question to get a plain-language answer plus the exact code that ran.'
                : 'Upload a dataset, then ask a question.'}
            </p>
          )}

          {/* Charts (stub) */}
          <StubPanel
            title="Charts"
            hint="Interactive (hover / zoom) charts auto-generated for your answers."
          />

          {/* Follow-up suggestions (stub) */}
          <StubPanel
            title="Suggested follow-ups"
            hint="Clickable next questions that carry the conversation context."
          />
        </section>
      </main>
    </div>
  )
}
