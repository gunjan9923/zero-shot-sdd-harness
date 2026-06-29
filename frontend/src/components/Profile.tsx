// Auto-profile panel — shows each column's dtype, missing-value count, and
// (for numeric columns) min/max/mean or (for categorical columns) top values.
// Populated automatically from the dataset's `profile` object on upload.

export interface ColumnProfile {
  type?: string
  missing?: number
  // Numeric stats
  min?: number | string | null
  max?: number | string | null
  mean?: number | string | null
  // Categorical stats — either a list of {value, count} or a value->count map.
  top?: Array<{ value: unknown; count: number }> | Record<string, number> | null
}

export type DatasetProfile = Record<string, ColumnProfile>

interface ProfileProps {
  /** The profile object from the dataset, or null while it is unavailable. */
  profile: DatasetProfile | null
  /** Total row count, used to contextualise missing-value counts. */
  rowCount?: number
}

function isNumericColumn(col: ColumnProfile): boolean {
  return col.min != null || col.max != null || col.mean != null
}

function fmtNum(v: number | string | null | undefined): string {
  if (v == null) return '—'
  const n = typeof v === 'string' ? Number(v) : v
  if (typeof n !== 'number' || Number.isNaN(n)) return String(v)
  // Compact, locale-aware; keep up to 4 significant decimals for small means.
  if (Number.isInteger(n)) return n.toLocaleString()
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 })
}

function topValues(col: ColumnProfile): Array<{ value: string; count: number }> {
  const t = col.top
  if (!t) return []
  if (Array.isArray(t)) {
    return t.map(item => ({ value: String(item.value), count: item.count }))
  }
  return Object.entries(t).map(([value, count]) => ({ value, count }))
}

export function Profile({ profile, rowCount }: ProfileProps) {
  // Nothing to render until a profile exists. The page only mounts this once a
  // dataset is uploaded, so this guards against a backend that returns null.
  if (!profile || Object.keys(profile).length === 0) {
    return (
      <section
        aria-label="Dataset profile"
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      >
        <h2 className="text-sm font-semibold text-gray-800">Profile</h2>
        <p className="mt-2 text-sm text-gray-400">
          No profile available for this dataset yet.
        </p>
      </section>
    )
  }

  const columns = Object.entries(profile)

  return (
    <section
      aria-label="Dataset profile"
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-800">Profile</h2>
        <span className="text-xs text-gray-400">
          {columns.length} column{columns.length === 1 ? '' : 's'}
          {typeof rowCount === 'number' ? ` · ${rowCount.toLocaleString()} rows` : ''}
        </span>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-gray-200 text-gray-500">
              <th className="py-2 pr-3 font-medium">Column</th>
              <th className="py-2 pr-3 font-medium">Type</th>
              <th className="py-2 pr-3 font-medium">Missing</th>
              <th className="py-2 font-medium">Summary</th>
            </tr>
          </thead>
          <tbody>
            {columns.map(([name, col]) => {
              const missing = col.missing ?? 0
              const missingPct =
                typeof rowCount === 'number' && rowCount > 0
                  ? ` (${((missing / rowCount) * 100).toFixed(missing === 0 ? 0 : 1)}%)`
                  : ''
              const numeric = isNumericColumn(col)
              const tops = topValues(col)
              return (
                <tr key={name} className="border-b border-gray-100 align-top last:border-0">
                  <td className="py-2 pr-3 font-medium text-gray-800">{name}</td>
                  <td className="py-2 pr-3">
                    <span className="inline-flex items-center rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-600">
                      {col.type ?? '—'}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-gray-600">
                    {missing === 0 ? (
                      <span className="text-gray-400">none</span>
                    ) : (
                      <span className="text-amber-700">
                        {missing.toLocaleString()}
                        {missingPct}
                      </span>
                    )}
                  </td>
                  <td className="py-2 text-gray-600">
                    {numeric ? (
                      <span className="inline-flex flex-wrap gap-x-3 gap-y-0.5">
                        <span>
                          <span className="text-gray-400">min</span> {fmtNum(col.min)}
                        </span>
                        <span>
                          <span className="text-gray-400">max</span> {fmtNum(col.max)}
                        </span>
                        <span>
                          <span className="text-gray-400">mean</span> {fmtNum(col.mean)}
                        </span>
                      </span>
                    ) : tops.length > 0 ? (
                      <span className="flex flex-wrap gap-1">
                        {tops.slice(0, 5).map((t, i) => (
                          <span
                            key={`${t.value}-${i}`}
                            className="inline-flex items-center gap-1 rounded-md bg-gray-50 px-1.5 py-0.5 ring-1 ring-inset ring-gray-200"
                            title={`${t.count.toLocaleString()} rows`}
                          >
                            <span className="max-w-[10rem] truncate text-gray-700">{t.value}</span>
                            <span className="text-gray-400">{t.count.toLocaleString()}</span>
                          </span>
                        ))}
                      </span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
