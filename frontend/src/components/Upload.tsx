'use client'

import { useRef, useState } from 'react'
import type { Dataset } from '@/lib/api'

interface UploadProps {
  dataset: Dataset | null
  uploading: boolean
  error: string | null
  onUpload: (file: File) => void
}

const ACCEPT = '.csv,.xlsx,.xls'

export function Upload({ dataset, uploading, error, onUpload }: UploadProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  function pick() {
    inputRef.current?.click()
  }

  function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    onUpload(files[0])
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    if (uploading) return
    onFiles(e.dataTransfer.files)
  }

  return (
    <section aria-label="Upload dataset">
      <div
        role="button"
        tabIndex={0}
        aria-disabled={uploading}
        onClick={pick}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            pick()
          }
        }}
        onDragOver={e => {
          e.preventDefault()
          if (!uploading) setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={[
          'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition',
          dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white hover:border-gray-400',
          uploading ? 'pointer-events-none opacity-60' : '',
        ].join(' ')}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={e => onFiles(e.target.files)}
          disabled={uploading}
        />
        {uploading ? (
          <span className="flex items-center gap-2 text-sm font-medium text-gray-600">
            <Spinner /> Uploading…
          </span>
        ) : (
          <>
            <p className="text-sm font-medium text-gray-700">
              Drag &amp; drop a CSV or Excel file here
            </p>
            <p className="mt-1 text-xs text-gray-400">or click to choose a file (.csv, .xlsx)</p>
          </>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {dataset && (
        <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm font-semibold text-gray-800">{dataset.name}</span>
            <span className="text-xs text-gray-500">
              {dataset.row_count.toLocaleString()} rows · {dataset.file_type.toUpperCase()}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {Object.keys(dataset.schema).map(col => (
              <span
                key={col}
                className="inline-flex items-center rounded-md bg-white px-2 py-0.5 text-xs font-medium text-gray-600 ring-1 ring-inset ring-gray-200"
                title={dataset.schema[col]}
              >
                {col}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600"
    />
  )
}
