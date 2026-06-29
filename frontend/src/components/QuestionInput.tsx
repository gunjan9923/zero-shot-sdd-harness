'use client'

interface QuestionInputProps {
  value: string
  onChange: (value: string) => void
  onAsk: () => void
  /** True when there is no dataset yet — disables the whole control. */
  noDataset: boolean
  loading: boolean
}

export function QuestionInput({ value, onChange, onAsk, noDataset, loading }: QuestionInputProps) {
  const canAsk = !noDataset && !loading && value.trim().length > 0

  function onKeyDown(e: React.KeyboardEvent) {
    // Cmd/Ctrl+Enter submits.
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canAsk) {
      e.preventDefault()
      onAsk()
    }
  }

  return (
    <div className="space-y-2">
      <label htmlFor="question" className="block text-sm font-medium text-gray-700">
        Ask a question
      </label>
      <textarea
        id="question"
        rows={3}
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={noDataset || loading}
        placeholder={
          noDataset
            ? 'Upload a dataset first…'
            : 'e.g. what is the total revenue? average order value by region?'
        }
        className="w-full rounded-lg border border-gray-300 p-3 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400"
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">Cmd/Ctrl + Enter to ask</span>
        <button
          type="button"
          onClick={onAsk}
          disabled={!canAsk}
          className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? 'Working…' : 'Ask'}
        </button>
      </div>
    </div>
  )
}
