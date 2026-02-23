import { formatBytes } from '../utils.js'

export default function StatsBar({ stats, rowCount, isFiltered }) {
  if (!stats) return null

  return (
    <div className="flex items-center gap-4 py-1.5 mb-2 text-[11px] text-slate-400 border-b border-slate-100">
      <span>
        <span className="font-medium text-slate-600">{stats.total_files?.toLocaleString()}</span>
        {' '}files
      </span>
      <span>
        <span className="font-medium text-slate-600">{formatBytes(stats.total_bytes)}</span>
        {' '}total
      </span>
      <span>
        <span className="font-medium text-slate-600">{stats.total_hosts}</span>
        {' '}host{stats.total_hosts !== 1 ? 's' : ''}
      </span>
      {stats.duplicate_sets > 0 && (
        <span className="text-amber-600">
          <span className="font-medium">{stats.duplicate_sets?.toLocaleString()}</span>
          {' '}duplicate set{stats.duplicate_sets !== 1 ? 's' : ''}
          {stats.wasted_bytes ? ` · ${formatBytes(stats.wasted_bytes)} total` : ''}
          {isFiltered && <span className="font-normal opacity-70"> (filtered)</span>}
        </span>
      )}
      {rowCount > 0 && (
        <span className="ml-auto">
          {rowCount.toLocaleString()} visible
        </span>
      )}
    </div>
  )
}
