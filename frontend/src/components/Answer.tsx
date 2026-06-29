// Renders an analysis result: prose answer, retry note, and the code panel.
// On failure, shows a clear failure message and still reveals the last code.

import type { Analysis } from '@/lib/api'
import { CodePanel } from './CodePanel'

interface AnswerProps {
  analysis: Analysis
}

export function Answer({ analysis }: AnswerProps) {
  const failed = analysis.status === 'failed'
  const retried = (analysis.retry_count ?? 0) > 0

  if (failed) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
        <p className="text-sm font-semibold text-amber-800">
          The agent couldn&apos;t produce a valid answer.
        </p>
        <p className="mt-1 text-sm text-amber-700">
          {analysis.error || 'It exhausted its retries while trying to write working code.'}
        </p>
        {retried && (
          <p className="mt-1 text-xs text-amber-600">Retried {analysis.retry_count} times.</p>
        )}
        {analysis.code ? (
          <CodePanel code={analysis.code} defaultOpen label="Show what it tried" />
        ) : (
          <p className="mt-2 text-xs text-amber-600">No code was produced.</p>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-900">
        {analysis.answer}
      </p>
      {retried && (
        <p className="mt-2 text-xs text-gray-400">Retried {analysis.retry_count} times.</p>
      )}
      {analysis.code && <CodePanel code={analysis.code} />}
    </div>
  )
}
