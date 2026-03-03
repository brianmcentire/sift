import { useEffect, useMemo, useRef, useState } from 'react'
import FileRow from './FileRow.jsx'

// Skeleton row name-column widths (varied to look natural)
const SKELETON_WIDTHS = ['w-40', 'w-56', 'w-32', 'w-48', 'w-36', 'w-52', 'w-28', 'w-44']
const SKELETON_COL_WIDTHS = { size: 'w-12 ml-auto', date: 'w-20', seen: 'w-20', type: 'w-10', hash: 'w-16', hosts: 'w-12' }

export const COLUMN_DEFS = {
  size:  { label: 'Size',      sortKey: 'size',  headerClass: 'text-right pr-4' },
  date:  { label: 'Modified',  sortKey: 'date',  headerClass: 'pr-4' },
  seen:  { label: 'Last Seen', sortKey: 'seen',  headerClass: 'pr-4' },
  type:  { label: 'Type',      sortKey: 'type',  headerClass: 'pr-4' },
  hash:  { label: 'Hash',      sortKey: 'hash',  headerClass: 'pr-4' },
  hosts: { label: 'Hosts',     sortKey: null,    headerClass: '' },
}

function SortIcon({ col, sortBy, sortDir }) {
  if (col !== sortBy) return <span className="text-slate-300 ml-0.5">↕</span>
  return <span className="text-blue-500 ml-0.5">{sortDir === 'asc' ? '↑' : '↓'}</span>
}

export default function FileTable({
  rows,
  hostColorMap,
  visibleColumns,
  columnOrder,
  sortBy,
  sortDir,
  onSort,
  onToggleDir,
  onFileClick,
  onCopyPath,
  onTypeClick,
  onDupHashClick,
  onDupSubtreeClick,
  onLoadMore,
  highlightedPaths,
  matchedDirPaths,
  expandedPaths,
  isLoading,
  filterActive,
}) {
  // Ordered list of visible non-name columns
  const orderedCols = columnOrder.filter(k => visibleColumns[k])
  const colCount = 1 + orderedCols.length
  const scrollRef = useRef(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(520)

  useEffect(() => {
    function updateHeight() {
      const next = Math.max(360, Math.floor(window.innerHeight * 0.68))
      setViewportHeight(next)
    }
    updateHeight()
    window.addEventListener('resize', updateHeight)
    return () => window.removeEventListener('resize', updateHeight)
  }, [])

  const rowHeights = useMemo(() => rows.map(row => {
    if (row.isGroupHeader) return 30
    if (row.isLoadMore) return 40
    return 34
  }), [rows])

  const prefixSums = useMemo(() => {
    const sums = new Array(rowHeights.length + 1)
    sums[0] = 0
    for (let i = 0; i < rowHeights.length; i++) sums[i + 1] = sums[i] + rowHeights[i]
    return sums
  }, [rowHeights])

  const totalHeight = prefixSums[prefixSums.length - 1] || 0

  const windowed = useMemo(() => {
    if (rows.length <= 200) {
      return {
        start: 0,
        end: rows.length,
      }
    }

    const top = Math.max(0, scrollTop - 300)
    const bottom = scrollTop + viewportHeight + 300
    let start = 0
    while (start < rows.length && prefixSums[start + 1] < top) start++
    let end = start
    while (end < rows.length && prefixSums[end] < bottom) end++
    return { start: Math.max(0, start), end: Math.min(rows.length, end + 1) }
  }, [rows.length, scrollTop, viewportHeight, prefixSums])

  const topPad = prefixSums[windowed.start] || 0
  const bottomPad = totalHeight - (prefixSums[windowed.end] || 0)
  const visibleRows = rows.slice(windowed.start, windowed.end)

  return (
    <div
      ref={scrollRef}
      className="overflow-x-auto overflow-y-auto"
      style={{ maxHeight: `${viewportHeight}px` }}
      onScroll={e => setScrollTop(e.currentTarget.scrollTop)}
    >
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="border-b border-slate-200">
            {/* Name — always first */}
            <th
              className="pb-2 pr-3 text-[10px] uppercase tracking-widest text-slate-500 font-medium cursor-pointer select-none hover:text-slate-800 transition-colors"
              onClick={() => onSort('name')}
            >
              Name <SortIcon col="name" sortBy={sortBy} sortDir={sortDir} />
            </th>

            {orderedCols.map(key => {
              const def = COLUMN_DEFS[key]
              return (
                <th
                  key={key}
                  onClick={() => def.sortKey && onSort(def.sortKey)}
                  className={`
                    pb-2 pr-4 text-[10px] uppercase tracking-widest font-medium text-slate-500
                    select-none transition-colors
                    ${def.headerClass}
                    ${def.sortKey ? 'cursor-pointer hover:text-slate-800' : ''}
                  `}
                >
                  {def.label}
                  {def.sortKey && <SortIcon col={def.sortKey} sortBy={sortBy} sortDir={sortDir} />}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {isLoading && rows.length === 0
            ? SKELETON_WIDTHS.map((w, i) => (
                <tr key={i} className="border-b border-slate-100 animate-pulse">
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-2 bg-slate-200 rounded shrink-0" />
                      <div className={`h-2.5 bg-slate-200 rounded ${w}`} />
                    </div>
                  </td>
                  {orderedCols.map(k => (
                    <td key={k} className="py-2 pr-4">
                      <div className={`h-2.5 bg-slate-200 rounded ${SKELETON_COL_WIDTHS[k] ?? 'w-16'}`} />
                    </td>
                  ))}
                </tr>
              ))
            : !isLoading && rows.length === 0
            ? (
                <tr>
                  <td colSpan={colCount} className="py-16 text-center text-slate-400 text-sm">
                    No files found.
                  </td>
                </tr>
              )
            : <>
                {topPad > 0 && (
                  <tr>
                    <td colSpan={colCount} style={{ height: `${topPad}px`, padding: 0 }} />
                  </tr>
                )}
                {visibleRows.map((row, i) => row.isGroupHeader ? (
                <tr key={`gh:${windowed.start + i}:${row.hash}`} className="bg-slate-100 border-t border-slate-200">
                  <td colSpan={colCount} className="py-1 px-4 text-xs text-slate-500 font-medium">
                    {row.hash.slice(0, 12)}… · {row.count} copies
                  </td>
                </tr>
              ) : row.isLoadMore ? (
                <tr key={`more:${row.fullPath}`} className="border-b border-slate-100">
                  <td colSpan={colCount} className="py-1.5 pr-3">
                    <div style={{ paddingLeft: row.depth * 20 + 16 }}>
                      <button
                        className="text-xs px-2 py-1 rounded border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                        onClick={() => onLoadMore?.(row.path)}
                      >
                        Load more
                      </button>
                    </div>
                  </td>
                </tr>
              ) : (
                <FileRow
                  key={`${row.fullPath}:${row.entry.presentHosts?.join(',')}`}
                  entry={row.entry}
                  parentPath={row.parentPath}
                  fullPath={row.fullPath}
                  fullDisplayPath={row.fullDisplayPath}
                  depth={row.depth}
                  driveContext={row.driveContext}
                  isExpanded={expandedPaths.has(row.fullPath)}
                  onToggleDir={onToggleDir}
                  onFileClick={onFileClick}
                  onCopyPath={onCopyPath}
                  onTypeClick={onTypeClick}
                  onDupHashClick={onDupHashClick}
                  onDupSubtreeClick={onDupSubtreeClick}
                  highlightedPaths={highlightedPaths}
                  matchedDirPaths={matchedDirPaths}
                  hostColorMap={hostColorMap}
                  orderedCols={orderedCols}
                  filterActive={filterActive}
                />
              ))}
                {bottomPad > 0 && (
                  <tr>
                    <td colSpan={colCount} style={{ height: `${bottomPad}px`, padding: 0 }} />
                  </tr>
                )}
              </>
          }
        </tbody>
      </table>
    </div>
  )
}
