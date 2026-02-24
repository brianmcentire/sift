import HostChips from './HostChips.jsx'
import SearchBar from './SearchBar.jsx'
import DirectorySearch from './DirectorySearch.jsx'
import FileTypeFilter from './FileTypeFilter.jsx'
import DupSizeFilter from './DupSizeFilter.jsx'
import DupOnlyToggle from './DupOnlyToggle.jsx'
import ColumnToggle from './ColumnToggle.jsx'

export default function Header({
  hosts,
  selectedHosts,
  setSelectedHosts,
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
  minDupSize,
  setMinDupSize,
  onlyDups,
  setOnlyDups,
  visibleColumns,
  setVisibleColumns,
  onReset,
}) {
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
          {/* Logo */}
          <span className="text-[15px] font-bold tracking-tight text-slate-800 mr-1 shrink-0">
            sift
          </span>

          {/* Directory search */}
          <DirectorySearch
            value={dirQuery}
            onChange={setDirQuery}
            className="w-44 shrink-0"
          />

          {/* Filename search */}
          <SearchBar
            value={filenameQuery}
            onChange={setFilenameQuery}
            placeholder="filename…"
            className="w-44 shrink-0"
          />

          {/* Hash search */}
          <SearchBar
            value={hashQuery}
            onChange={setHashQuery}
            placeholder="# hash…"
            className="w-44 shrink-0"
          />

          {/* Spacer */}
          <div className="flex-1" />

          {/* Dup-only toggle */}
          <DupOnlyToggle value={onlyDups} onChange={setOnlyDups} />

          {/* Min dup size filter */}
          <DupSizeFilter
            value={minDupSize}
            onChange={setMinDupSize}
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

        {/* Bottom row: host chips */}
        {hosts.length > 0 && (
          <div className="mt-2">
            <HostChips
              hosts={hosts}
              selectedHosts={selectedHosts}
              setSelectedHosts={setSelectedHosts}
              hostColorMap={hostColorMap}
            />
          </div>
        )}
      </div>
    </header>
  )
}
