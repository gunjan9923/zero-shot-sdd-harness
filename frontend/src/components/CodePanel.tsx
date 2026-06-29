// Collapsible "Show code" panel — native <details>/<summary>, no JS toggle.

interface CodePanelProps {
  code: string
  /** When true, the panel starts open (used on failure to surface what it tried). */
  defaultOpen?: boolean
  label?: string
}

export function CodePanel({ code, defaultOpen = false, label = 'Show code' }: CodePanelProps) {
  return (
    <details open={defaultOpen} className="group mt-3 rounded-lg border border-gray-200 bg-gray-50">
      <summary className="cursor-pointer select-none px-4 py-2 text-sm font-medium text-gray-700 marker:content-none">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="text-gray-400 transition group-open:rotate-90">▶</span>
          {label}
        </span>
      </summary>
      <pre className="overflow-x-auto border-t border-gray-200 px-4 py-3 text-xs leading-relaxed">
        <code className="font-mono text-gray-800">{code}</code>
      </pre>
    </details>
  )
}
