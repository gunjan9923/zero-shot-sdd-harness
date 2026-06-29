'use client'

// Interactive chart renderer. The backend returns a Vega-Lite spec (with the
// data computed locally and embedded). We render it with vega-embed in a
// client-side effect — no SSR, which keeps the static export clean and avoids
// React-19 peer-dep friction from wrapper libraries. Interactivity (hover
// tooltips + scroll/drag zoom) is enabled via the embed options below.

import { useEffect, useRef, useState } from 'react'

// Loaded lazily inside the effect so vega/vega-lite never enters the SSR/export
// bundle path. Typed loosely because the chart spec is produced by the LLM.
type VegaSpec = Record<string, unknown>

interface ChartProps {
  /** A Vega-Lite spec object from the analysis, or null when no chart applies. */
  spec: VegaSpec | null | undefined
}

export function Chart({ spec }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Only render when a real spec is present.
    if (!spec || typeof spec !== 'object' || Object.keys(spec).length === 0) {
      return
    }

    let cancelled = false
    let view: { finalize: () => void } | null = null

    setError(null)

    // Dynamic import keeps vega-embed out of the server/export pass.
    import('vega-embed')
      .then(async ({ default: embed }) => {
        if (cancelled || !containerRef.current) return
        const result = await embed(containerRef.current, spec as never, {
          actions: { export: true, source: false, compiled: false, editor: false },
          tooltip: true, // hover tooltips
          renderer: 'canvas',
          // Make the chart responsive to its container width.
          width: 'container' as unknown as number,
        })
        if (cancelled) {
          result.view.finalize()
          return
        }
        view = result.view
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(
          err instanceof Error ? err.message : 'Could not render the chart for this answer.'
        )
      })

    return () => {
      cancelled = true
      if (view) view.finalize()
    }
  }, [spec])

  // Render nothing at all when there is no chart for this answer — the chart
  // area simply does not appear, rather than showing an empty box.
  if (!spec || typeof spec !== 'object' || Object.keys(spec).length === 0) {
    return null
  }

  return (
    <section
      aria-label="Chart"
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <h2 className="mb-3 text-sm font-semibold text-gray-800">Chart</h2>
      {error ? (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      ) : (
        <div ref={containerRef} className="w-full overflow-x-auto" data-testid="vega-chart" />
      )}
      <p className="mt-2 text-xs text-gray-400">Hover for values · scroll or drag to zoom.</p>
    </section>
  )
}
