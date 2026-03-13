import { useRef, useState, useEffect } from 'react'
import { formatBytes } from '../utils.js'

function timeAgo(iso) {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 60000) return 'just now'
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`
  if (ms < 86400000) return `${Math.floor(ms / 3600000)}h ago`
  return `${Math.floor(ms / 86400000)}d ago`
}

export default function StatsBar({ stats, rowCount, isFiltered }) {
  const lastStaleTimeRef = useRef(0)
  const [showStale, setShowStale] = useState(false)

  const freshness = stats?.data_freshness
  const isStale = freshness && freshness !== 'fresh'

  useEffect(() => {
    if (isStale) {
      lastStaleTimeRef.current = Date.now()
      setShowStale(true)
    } else if (showStale) {
      // Keep showing for 3s after transitioning to fresh
      const elapsed = Date.now() - lastStaleTimeRef.current
      const remaining = Math.max(0, 3000 - elapsed)
      const timer = setTimeout(() => setShowStale(false), remaining)
      return () => clearTimeout(timer)
    }
  }, [isStale, showStale])

  if (!stats) return null

  let freshnessText = null
  if (isStale || showStale) {
    if (freshness === 'building') {
      freshnessText = '(updating\u2026)'
    } else {
      const ago = timeAgo(stats.aggregated_at)
      if (ago) freshnessText = `(as of ${ago})`
    }
  }

  return (
    <div data-testid="stats-bar" className="flex items-center gap-4 py-1.5 mb-2 text-[11px] text-slate-400 border-b border-slate-100">
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
          {freshnessText && <span className="font-normal text-slate-400 ml-1">{freshnessText}</span>}
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
