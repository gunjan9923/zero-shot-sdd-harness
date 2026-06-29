// Reusable "coming soon" stub primitives. Everything rendered through these
// reads as intentional (muted + tagged), never as a bug.

export function ComingSoonPill() {
  return (
    <span className="inline-flex items-center rounded-full bg-gray-200 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-500">
      coming soon
    </span>
  )
}

interface StubPanelProps {
  title: string
  /** Optional one-line hint about what this becomes later. */
  hint?: string
}

/** A muted, dashed-border placeholder panel tagged "coming soon". */
export function StubPanel({ title, hint }: StubPanelProps) {
  return (
    <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 opacity-70">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-gray-500">{title}</span>
        <ComingSoonPill />
      </div>
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  )
}
