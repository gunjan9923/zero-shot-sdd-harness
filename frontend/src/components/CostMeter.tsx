'use client'

// Cost awareness. Shows tokens + estimated cost for the latest answer and a
// running daily total. Rendered in the header; compact by design.

import type { Analysis, DailyCost } from '@/lib/api'

interface CostMeterProps {
  /** The most recent analysis (for per-question tokens/cost), if any. */
  analysis: Analysis | null
  /** Running daily total, refreshed after each answer. */
  daily: DailyCost | null
}

function usd(n: number | null | undefined): string {
  if (n == null) return '$0.00'
  if (n > 0 && n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

export function CostMeter({ analysis, daily }: CostMeterProps) {
  const tokens = analysis?.tokens ?? null
  const cost = analysis?.estimated_cost_usd ?? null

  return (
    <span
      className="inline-flex items-center gap-2 rounded-md border border-gray-200 bg-white px-2.5 py-1 text-xs text-gray-600"
      title="Estimated cost — best-effort, configurable per-token pricing"
    >
      <span>
        <span className="text-gray-400">this q:</span>{' '}
        {tokens != null ? `${tokens.toLocaleString()} tok · ${usd(cost)}` : '—'}
      </span>
      <span className="text-gray-300">|</span>
      <span>
        <span className="text-gray-400">today:</span>{' '}
        {daily ? `${daily.total_tokens.toLocaleString()} tok · ${usd(daily.total_cost_usd)}` : '—'}
      </span>
    </span>
  )
}
