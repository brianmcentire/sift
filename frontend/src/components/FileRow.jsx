import { formatBytes, formatDate, formatISODate } from '../utils.js'
import HostBadge from './HostBadge.jsx'
import HashCell from './HashCell.jsx'

// Cell renderers keyed by column key.
// Each receives ({ entry, opts }) and returns a <td>.
const CELL_RENDERERS = {
  size: ({ entry }) => (
    <td key="size" className="py-1.5 pr-4 text-right text-sm text-slate-500 whitespace-nowrap tabular-nums">
      {formatBytes(entry.entry_type === 'dir' ? entry.total_bytes : entry.size_bytes)}
    </td>
  ),

  date: ({ entry }) => (
    <td key="date" className="py-1.5 pr-4 text-sm text-slate-400 whitespace-nowrap tabular-nums">
      {entry.entry_type === 'dir' ? '' : formatDate(entry.mtime)}
    </td>
  ),

  seen: ({ entry }) => (
    <td key="seen" className="py-1.5 pr-4 text-sm text-slate-400 whitespace-nowrap tabular-nums">
      {entry.entry_type === 'dir' ? '' : formatISODate(entry.last_seen_at)}
    </td>
  ),

  type: ({ entry, onTypeClick }) => (
    <td
      key="type"
      className="py-1.5 pr-4 text-[12px] text-slate-400 whitespace-nowrap"
      onClick={e => {
        if (entry.entry_type === 'file' && entry.file_category && onTypeClick) {
          e.stopPropagation()
          onTypeClick(entry.file_category)
        }
      }}
    >
      {entry.entry_type === 'dir' ? '' : (
        <span className={entry.file_category && onTypeClick ? 'cursor-pointer hover:text-slate-600' : ''}>
          {entry.file_category || ''}
        </span>
      )}
    </td>
  ),

  hash: ({ entry, extraCopies, fullPath, onDupHashClick }) => (
    <td key="hash" className="py-1.5 pr-4">
      {entry.entry_type === 'dir' ? (
        extraCopies > 0 ? (
          <span
            className={`text-[11px] text-amber-600 font-medium ${
              extraCopies === 1 && onDupHashClick
                ? 'cursor-pointer hover:text-amber-800 hover:underline'
                : ''
            }`}
            title={extraCopies === 1 && onDupHashClick ? 'Show all copies' : undefined}
            onClick={extraCopies === 1 && onDupHashClick
              ? e => { e.stopPropagation(); onDupHashClick(fullPath, entry) }
              : undefined}
          >
            {extraCopies} extra cop{extraCopies !== 1 ? 'ies' : 'y'}
          </span>
        ) : null
      ) : (
        <HashCell hash={entry.hash} />
      )}
    </td>
  ),

  hosts: ({ entry, allHostsSet, hostColorMap }) => (
    <td key="hosts" className="py-1.5">
      <div className="flex items-center gap-1 flex-wrap">
        {[...allHostsSet].map(h => (
          <HostBadge key={h} host={h} hostColorMap={hostColorMap} />
        ))}
      </div>
    </td>
  ),
}

export default function FileRow({
  entry,
  parentPath,
  fullPath,
  fullDisplayPath,
  depth,
  isExpanded,
  onToggleDir,
  onFileClick,
  onCopyPath,
  onTypeClick,
  onDupHashClick,
  highlightedPaths,
  matchedDirPaths,
  hostColorMap,
  orderedCols,
  filterActive,
}) {
  const isDir = entry.entry_type === 'dir'

  // Duplicate detection:
  //   dup_count > 0       → same-host duplicate (server scopes this to the queried host)
  //   presentHosts.length > 1 → file exists on multiple *selected* hosts (cross-host dup,
  //                             only fires when the user has more than one host selected)
  // other_hosts is informational (shown in host badges) but does NOT drive amber
  // highlighting — a file on a non-selected host is not a "dup" from the current view.
  const isDup = !isDir && (
    entry.dup_count > 0 ||
    (entry.presentHosts?.length ?? 0) > 1
  )
  const isHardLinked = !isDir && Boolean(entry.is_hard_linked)

  const otherHostList = entry.other_hosts
    ? entry.other_hosts.split(',').map(h => h.trim()).filter(Boolean)
    : []
  const allHostsSet = new Set([...(entry.presentHosts || []), ...otherHostList])

  // Extra copies = files in dup groups minus the distinct dup groups
  const extraCopies = Math.max(0, (entry.dup_count || 0) - (entry.dup_hash_count || 0))

  // Blue highlight: this is the file (or one of the files) the user navigated from
  const isHighlighted = !!(highlightedPaths?.size && highlightedPaths.has((fullPath || '').toLowerCase()))
  // Soft blue: this dir matched the directory search (tree mode only)
  const isMatchedDir = !filterActive && isDir && !!(matchedDirPaths?.size && matchedDirPaths.has(fullPath))

  // When filter is active (or search mode), show parent path as context below filename
  const indent = filterActive ? 0 : depth * 20
  const contextPath = filterActive && !isDir
    ? (entry.path_display
        ? entry.path_display.split('/').slice(0, -1).join('/') || '/'
        : parentPath)
    : null

  function handleRowClick() {
    if (isDir) {
      onToggleDir(fullPath)
    } else {
      onFileClick?.(entry)
    }
  }

  const cellOpts = { entry, extraCopies, allHostsSet, hostColorMap, onTypeClick, fullPath, onDupHashClick }

  return (
    <tr
      className={`
        group border-b border-slate-100
        ${isHighlighted ? 'bg-blue-100 hover:bg-blue-200' : isDup ? 'bg-amber-50 hover:bg-amber-100' : isHardLinked ? 'bg-orange-50 hover:bg-orange-100' : isMatchedDir ? 'bg-blue-50 hover:bg-blue-100' : 'hover:bg-slate-100'}
        ${isDir || onFileClick ? 'cursor-pointer' : ''}
        transition-colors duration-100
      `}
      onClick={handleRowClick}
    >
      {/* Name — always first */}
      <td className="py-1.5 pr-3 max-w-xs">
        <div className="flex items-center gap-1 min-w-0" style={{ paddingLeft: indent }}>
          {isDir
            ? <span className="text-[11px] text-slate-400 shrink-0 w-3 text-center select-none">{isExpanded ? '▼' : '▶'}</span>
            : <span className="w-3 shrink-0" />
          }
          <div className="min-w-0 flex items-center gap-1">
            <div className="min-w-0">
              <div
                className={`truncate text-sm leading-tight ${isDir ? 'font-medium text-slate-800' : 'text-slate-700'}`}
                title={entry.segment_display || entry.segment}
              >
                {entry.segment_display || entry.segment}{isDir && '/'}
              </div>
              {contextPath && (
                <div className="truncate text-[11px] text-slate-400 font-mono leading-tight mt-0.5" title={contextPath}>
                  {contextPath}
                </div>
              )}
            </div>
            {isDir && onCopyPath && (
              <button
                onClick={e => { e.stopPropagation(); onCopyPath(fullDisplayPath || fullPath) }}
                className="opacity-0 group-hover:opacity-100 shrink-0 ml-1 text-slate-300 hover:text-slate-500 transition-opacity leading-none"
                title="Copy path to clipboard"
              >
                ⧉
              </button>
            )}
          </div>
        </div>
      </td>

      {/* Dynamic columns in user-defined order */}
      {orderedCols.map(key => {
        const renderer = CELL_RENDERERS[key]
        return renderer ? renderer(cellOpts) : null
      })}
    </tr>
  )
}
