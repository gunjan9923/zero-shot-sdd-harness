'use client'

// Follow-up suggestion chips. The backend returns 2–3 suggested next questions
// with each answer; clicking a chip submits it as the next question, carrying
// the conversation context (the page threads context on submit).

interface FollowupsProps {
  /** Suggested next questions from the analysis, or null/empty when none. */
  followups: string[] | null | undefined
  /** Submit a chip as the next question. */
  onPick: (question: string) => void
  /** Disable chips while an analysis is in flight. */
  disabled?: boolean
}

export function Followups({ followups, onPick, disabled }: FollowupsProps) {
  const items = (followups ?? []).filter(
    (q): q is string => typeof q === 'string' && q.trim().length > 0
  )

  // No suggestions → render nothing (the section simply does not appear).
  if (items.length === 0) return null

  return (
    <section aria-label="Suggested follow-ups" className="space-y-2">
      <h2 className="text-sm font-medium text-gray-700">Suggested follow-ups</h2>
      <div className="flex flex-wrap gap-2">
        {items.map((q, i) => (
          <button
            key={`${i}-${q}`}
            type="button"
            disabled={disabled}
            onClick={() => onPick(q)}
            className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm text-blue-700 transition hover:border-blue-400 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span aria-hidden className="text-blue-400">
              ↳
            </span>
            {q}
          </button>
        ))}
      </div>
    </section>
  )
}
