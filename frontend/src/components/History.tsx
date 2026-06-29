'use client'

// Run-history audit trail. Lists past analyses for the active dataset with the
// question, timestamp, cost, and the exact code that ran (collapsible).

import type { HistoryItem } from '@/lib/api'
import { CodePanel } from './CodePanel'

interface HistoryProps {
  items: HistoryItem[]
  onClose: () => void
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function History({ items, onClose }: HistoryProps) {
  return (
    <section
      aria-label="Run history"
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-800">History</h2>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-gray-400 hover:text-gray-700"
        >
          Close
        </button>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-gray-400">No past analyses for this dataset yet.</p>
      ) : (
        <ul className="space-y-3">
          {items.map(it => (
            <li key={it.analysis_id} className="border-b border-gray-100 pb-3 last:border-0">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium text-gray-800">{it.question}</p>
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase ${
                    it.status === 'completed'
                      ? 'bg-green-50 text-green-700'
                      : 'bg-amber-50 text-amber-700'
                  }`}
                >
                  {it.status}
                </span>
              </div>
              {it.answer && (
                <p className="mt-1 line-clamp-2 text-sm text-gray-600">{it.answer}</p>
              )}
              <div className="mt-1 flex items-center gap-3 text-[11px] text-gray-400">
                <span>{fmtTime(it.created_at)}</span>
                {it.estimated_cost_usd != null && (
                  <span>${it.estimated_cost_usd.toFixed(4)}</span>
                )}
              </div>
              {it.code && <CodePanel code={it.code} label="Show code" />}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
