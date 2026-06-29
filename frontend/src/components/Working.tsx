// In-flight analysis indicator. Phase 3 replaces this with streamed live steps.

export function Working() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-600 shadow-sm"
    >
      <span
        aria-hidden
        className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600"
      />
      Working…
    </div>
  )
}
