import HostChips from './HostChips.jsx'
import HiddenHostDropdown from './HiddenHostDropdown.jsx'
import SearchBar from './SearchBar.jsx'
import DirectorySearch from './DirectorySearch.jsx'
import FileTypeFilter from './FileTypeFilter.jsx'
import DupSizeFilter from './DupSizeFilter.jsx'
import DupOnlyToggle from './DupOnlyToggle.jsx'
import ColumnToggle from './ColumnToggle.jsx'

export default function Header({
  viewMode,
  onToggleViewMode,
  hosts,
  hiddenHosts,
  selectedHosts,
  setSelectedHosts,
  promotedHiddenHosts,
  setPromotedHiddenHosts,
  hostColorMap,
  dirQuery,
  setDirQuery,
  filenameQuery,
  setFilenameQuery,
  hashQuery,
  setHashQuery,
  categoryFilter,
  setCategoryFilter,
  availableCategories,
  minSize,
  setMinSize,
  onlyDups,
  setOnlyDups,
  visibleColumns,
  setVisibleColumns,
  onReset,
  apiPendingCount,
}) {
  const isTree = viewMode === 'tree'

  return (
    <header className="
      sticky top-0 z-40
      bg-white/90 backdrop-blur-md
      border-b border-slate-200
      shadow-sm
    ">
      <div className="max-w-screen-2xl mx-auto px-4 py-2">
        {/* Top row: logo + search bars + controls */}
        <div className="flex items-center gap-3 flex-wrap">
          {/* App mode toggle */}
          <button
            data-testid="view-mode"
            onClick={onToggleViewMode}
            className="text-[13px] font-bold tracking-tight text-slate-800 mr-1 shrink-0 px-2 py-1 rounded-md hover:bg-slate-100 transition-colors"
            title={isTree ? 'Switch to List View' : 'Switch to Tree View'}
          >
            sift · {isTree ? 'Tree View' : 'List View'}
          </button>

          {/* Directory search */}
          <DirectorySearch
            value={dirQuery}
            onChange={setDirQuery}
            placeholder={isTree ? 'folder to open' : 'path contains'}
            className="w-44 shrink-0"
          />

          {/* Filename search */}
          <SearchBar
            value={filenameQuery}
            onChange={setFilenameQuery}
            placeholder="filename contains"
            className="w-44 shrink-0"
          />

          {/* Hash search */}
          <SearchBar
            value={hashQuery}
            onChange={setHashQuery}
            placeholder="hash or partial"
            className="w-44 shrink-0"
            data-testid="hash-search"
          />

          {/* Spacer */}
          <div className="flex-1" />

          {/* Dup-only toggle */}
          <DupOnlyToggle value={onlyDups} onChange={setOnlyDups} />

          {/* Min size filter */}
          <DupSizeFilter
            value={minSize}
            onChange={setMinSize}
          />

          {/* Type filter */}
          <FileTypeFilter
            value={categoryFilter}
            onChange={setCategoryFilter}
            categories={availableCategories}
          />

          {/* Column toggle */}
          <ColumnToggle
            visibleColumns={visibleColumns}
            setVisibleColumns={setVisibleColumns}
          />

          {/* Reset */}
          <button
            data-testid="reset-button"
            onClick={onReset}
            title="Clear all filters and reset view"
            className="
              px-2.5 py-1.5 text-sm
              border border-slate-200 rounded-lg bg-white
              text-slate-500 hover:text-slate-800 hover:bg-slate-50 cursor-pointer
              transition-all duration-150 whitespace-nowrap
            "
          >
            Reset
          </button>
        </div>

        {/* Bottom row: host chips + API activity */}
        {hosts.length > 0 && (
          <div className="mt-2 flex items-center justify-between gap-3">
            <div className="min-w-0 flex-1 flex items-center gap-2">
              <HostChips
                hosts={hosts}
                promotedHiddenHosts={hiddenHosts.filter(h => promotedHiddenHosts.has(h.host))}
                selectedHosts={selectedHosts}
                setSelectedHosts={setSelectedHosts}
                hostColorMap={hostColorMap}
              />
              {hiddenHosts.length > 0 && (
                <HiddenHostDropdown
                  hiddenHosts={hiddenHosts}
                  selectedHosts={selectedHosts}
                  setSelectedHosts={setSelectedHosts}
                  promotedHiddenHosts={promotedHiddenHosts}
                  setPromotedHiddenHosts={setPromotedHiddenHosts}
                  hostColorMap={hostColorMap}
                />
              )}
            </div>

            <div
              data-testid="api-activity"
              data-state={apiPendingCount > 0 ? 'busy' : 'idle'}
              data-count={String(apiPendingCount)}
              className="shrink-0 flex items-center gap-2 text-[11px] text-slate-500"
            >
              <span>API</span>
              {apiPendingCount > 0 ? (
                <span className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-blue-700 font-medium">
                  <span className="h-2 w-2 rounded-full bg-blue-500" />
                  {apiPendingCount}
                </span>
              ) : (
                <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-emerald-700 font-medium">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </header>
  )
}
