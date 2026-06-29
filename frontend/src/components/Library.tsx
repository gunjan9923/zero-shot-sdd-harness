'use client'

// Dataset library sidebar. Lists persisted datasets; click to load one as the
// primary dataset, check "join" to include it in a multi-file question, or
// delete it. Persists across sessions (backed by the local store + DB).

import type { DatasetListItem } from '@/lib/api'

interface LibraryProps {
  datasets: DatasetListItem[]
  /** Currently-active (primary) dataset id. */
  activeId: string | null
  /** Additional dataset ids included for a multi-file query. */
  includedIds: string[]
  onSelect: (id: string) => void
  onToggleInclude: (id: string) => void
  onDelete: (id: string) => void
}

export function Library({
  datasets,
  activeId,
  includedIds,
  onSelect,
  onToggleInclude,
  onDelete,
}: LibraryProps) {
  return (
    <section
      aria-label="Dataset library"
      className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
    >
      <h2 className="mb-2 text-sm font-semibold text-gray-800">Dataset library</h2>
      {datasets.length === 0 ? (
        <p className="text-xs text-gray-400">
          Uploaded datasets appear here and persist across sessions.
        </p>
      ) : (
        <ul className="space-y-1">
          {datasets.map(ds => {
            const isActive = ds.dataset_id === activeId
            const isIncluded = includedIds.includes(ds.dataset_id)
            return (
              <li
                key={ds.dataset_id}
                className={`group rounded-md border p-2 ${
                  isActive ? 'border-blue-300 bg-blue-50' : 'border-gray-100 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onSelect(ds.dataset_id)}
                    className="min-w-0 flex-1 text-left"
                    title="Use as the primary dataset"
                  >
                    <span className="block truncate text-sm font-medium text-gray-800">
                      {ds.name}
                    </span>
                    <span className="block text-[11px] text-gray-400">
                      {ds.row_count.toLocaleString()} rows · {ds.file_type}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(ds.dataset_id)}
                    title="Delete dataset"
                    className="rounded p-1 text-gray-300 opacity-0 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100"
                    aria-label={`Delete ${ds.name}`}
                  >
                    🗑
                  </button>
                </div>
                {!isActive && (
                  <label className="mt-1 flex cursor-pointer items-center gap-1.5 text-[11px] text-gray-500">
                    <input
                      type="checkbox"
                      checked={isIncluded}
                      onChange={() => onToggleInclude(ds.dataset_id)}
                      className="h-3 w-3 rounded border-gray-300"
                    />
                    join with primary
                  </label>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
