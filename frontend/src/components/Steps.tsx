'use client'

// Live agent progress. The SSE stream emits node-status steps; we show them in
// order with the current one spinning and completed ones checked.

const LABELS: Record<string, string> = {
  planning: 'Planning the approach',
  generating_code: 'Writing pandas code',
  running_code: 'Running code on your data',
  finalizing: 'Composing the answer',
  building_chart: 'Building chart',
  suggesting_followups: 'Suggesting follow-ups',
  error: 'Encountered an error',
}

interface StepsProps {
  /** Ordered step keys received so far from the stream. */
  steps: string[]
}

export function Steps({ steps }: StepsProps) {
  if (steps.length === 0) return null
  return (
    <section
      aria-label="Progress"
      className="rounded-lg border border-blue-200 bg-blue-50 p-4"
    >
      <ol className="space-y-1.5">
        {steps.map((step, i) => {
          const last = i === steps.length - 1
          return (
            <li key={`${i}-${step}`} className="flex items-center gap-2 text-sm">
              {last ? (
                <span
                  aria-hidden
                  className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-blue-300 border-t-blue-600"
                />
              ) : (
                <span aria-hidden className="text-blue-500">
                  ✓
                </span>
              )}
              <span className={last ? 'font-medium text-blue-800' : 'text-blue-600'}>
                {LABELS[step] ?? step}
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
