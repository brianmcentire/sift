import FileRow from './FileRow.jsx'

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
  highlightedPaths,
  matchedDirPaths,
  expandedPaths,
  isLoading,
  filterActive,
}) {
  // Ordered list of visible non-name columns
  const orderedCols = columnOrder.filter(k => visibleColumns[k])

  if (isLoading && rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400 text-sm">
        Loading…
      </div>
    )
  }

  if (!isLoading && rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400 text-sm">
        No files found.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
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
          {rows.map(({ entry, parentPath, fullPath, fullDisplayPath, depth }) => (
            <FileRow
              key={`${fullPath}:${entry.presentHosts?.join(',')}`}
              entry={entry}
              parentPath={parentPath}
              fullPath={fullPath}
              fullDisplayPath={fullDisplayPath}
              depth={depth}
              isExpanded={expandedPaths.has(fullPath)}
              onToggleDir={onToggleDir}
              onFileClick={onFileClick}
              onCopyPath={onCopyPath}
              onTypeClick={onTypeClick}
              onDupHashClick={onDupHashClick}
              highlightedPaths={highlightedPaths}
              matchedDirPaths={matchedDirPaths}
              hostColorMap={hostColorMap}
              orderedCols={orderedCols}
              filterActive={filterActive}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}
