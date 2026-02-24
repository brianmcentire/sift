import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { api } from './api.js'
import { joinPath, mergeEntries, sortEntries, hostColor, fileEntryToRow, sortFileEntries } from './utils.js'
import Header from './components/Header.jsx'
import StatsBar from './components/StatsBar.jsx'
import FileTable from './components/FileTable.jsx'

export default function App() {
  // ── Host state ──────────────────────────────────────────────────────────
  const [hosts, setHosts] = useState([])
  const [selectedHosts, setSelectedHosts] = useState(new Set())

  // ── Navigation state ────────────────────────────────────────────────────
  const [currentPath, setCurrentPath] = useState('/')
  const [expandedPaths, setExpandedPaths] = useState(new Set())

  // ── Search / filter state ───────────────────────────────────────────────
  const [dirQuery, setDirQuery] = useState('')
  const [debouncedDirQuery, setDebouncedDirQuery] = useState('')
  const [filenameQuery, setFilenameQuery] = useState('')
  const [debouncedFilenameQuery, setDebouncedFilenameQuery] = useState('')
  const [hashQuery, setHashQuery] = useState('')
  const [matchedDirPaths, setMatchedDirPaths] = useState(new Set()) // lowercase dir paths matched by dir query
  const [filenameResults, setFilenameResults] = useState(null)  // null | FileEntry[]
  const [hashResults, setHashResults] = useState(null)          // null | FileEntry[]
  const [pinnedResults, setPinnedResults] = useState(null)      // null | FileEntry[]
  const [highlightedPaths, setHighlightedPaths] = useState(new Set()) // paths (lowercase) to blue-highlight in results
  const [categoryFilter, setCategoryFilter] = useState(new Set())
  const [minDupSize, setMinDupSize] = useState(0)
  const [onlyDups, setOnlyDups] = useState(false)

  // ── Display state ───────────────────────────────────────────────────────
  const [visibleColumns, setVisibleColumns] = useState({ size: true, date: true, seen: true, type: true, hash: true, hosts: true })
  const [columnOrder] = useState(['size', 'date', 'seen', 'type', 'hash', 'hosts'])
  const [sortBy, setSortBy] = useState('name')
  const [sortDir, setSortDir] = useState('asc')

  // ── Clipboard toast ─────────────────────────────────────────────────────
  const [clipboardToast, setClipboardToast] = useState(false)

  // ── Data cache ──────────────────────────────────────────────────────────
  const cacheRef = useRef(new Map())
  const [cacheVersion, setCacheVersion] = useState(0)
  const [lsFetchKey, setLsFetchKey] = useState(0)
  const minDupSizeRef = useRef(minDupSize)

  // ── Stats ───────────────────────────────────────────────────────────────
  const [stats, setStats] = useState(null)

  // ── Loading ─────────────────────────────────────────────────────────────
  const [loadingPaths, setLoadingPaths] = useState(new Set())

  // ── Host color map ──────────────────────────────────────────────────────
  const hostColorMap = useMemo(() => {
    const m = new Map()
    hosts.forEach((h, i) => m.set(h.host, hostColor(i)))
    return m
  }, [hosts])

  // ── Debounce dir + filename queries ─────────────────────────────────────
  useEffect(() => {
    const t = setTimeout(() => setDebouncedDirQuery(dirQuery), 150)
    return () => clearTimeout(t)
  }, [dirQuery])

  useEffect(() => {
    const t = setTimeout(() => setDebouncedFilenameQuery(filenameQuery), 150)
    return () => clearTimeout(t)
  }, [filenameQuery])

  // ── Filename search (server-side) ────────────────────────────────────────
  useEffect(() => {
    if (debouncedFilenameQuery.length >= 2) {
      api.files({ iname: `*${debouncedFilenameQuery}*`, limit: 500 })
        .then(setFilenameResults)
        .catch(() => setFilenameResults([]))
    } else {
      setFilenameResults(null)
    }
  }, [debouncedFilenameQuery])

  // ── Hash search ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (hashQuery.length >= 4) {
      api.files({ hash: hashQuery, limit: 500 })
        .then(setHashResults)
        .catch(() => setHashResults([]))
    } else {
      setHashResults(null)
    }
  }, [hashQuery])

  // ── Initial load ─────────────────────────────────────────────────────────
  useEffect(() => {
    api.hosts()
      .then(data => {
        setHosts(data)
        setSelectedHosts(new Set(data.map(h => h.host)))
      })
      .catch(() => {})
  }, [])

  // ── Stats (re-fetched when minDupSize or categoryFilter changes) ─────────
  useEffect(() => {
    const params = { min_size: minDupSize }
    if (categoryFilter.size > 0) params.categories = [...categoryFilter].join(',')
    api.stats(params)
      .then(setStats)
      .catch(() => {})
  }, [minDupSize, categoryFilter])

  // ── When minDupSize changes, bust the ls cache so dup counts refresh ──────
  useEffect(() => {
    minDupSizeRef.current = minDupSize
    cacheRef.current.clear()
    setExpandedPaths(new Set())
    setLsFetchKey(k => k + 1)
  }, [minDupSize])

  // ── Fetch ls data for a path (all hosts) ─────────────────────────────────
  const fetchPath = useCallback(async (path, hostList) => {
    const toFetch = hostList.filter(h => !cacheRef.current.has(`${h.host}:${path}`))
    if (toFetch.length === 0) return

    setLoadingPaths(prev => new Set([...prev, path]))

    await Promise.all(toFetch.map(async h => {
      const key = `${h.host}:${path}`
      try {
        const data = await api.ls(path, h.host, minDupSizeRef.current)
        cacheRef.current.set(key, Array.isArray(data) ? data : [])
      } catch {
        cacheRef.current.set(key, [])
      }
    }))

    setLoadingPaths(prev => {
      const next = new Set(prev)
      next.delete(path)
      return next
    })
    setCacheVersion(v => v + 1)
  }, [])

  // ── Directory search → expand tree to matching dirs ─────────────────────
  // NOTE: must be after `fetchPath` useCallback to avoid TDZ
  useEffect(() => {
    if (debouncedDirQuery.length < 2) {
      setMatchedDirPaths(new Set())
      return
    }
    api.directories(debouncedDirQuery)
      .then(dirs => {
        if (!dirs || dirs.length === 0) {
          setMatchedDirPaths(new Set())
          return
        }
        const toExpand = new Set()
        const matched = new Set()
        dirs.forEach(d => {
          const p = d.dir_path
          matched.add(p)
          // Add ancestor paths (not the match itself) so the tree opens down to each match
          const parts = p.split('/').filter(Boolean)
          for (let i = 1; i < parts.length; i++) {
            toExpand.add('/' + parts.slice(0, i).join('/'))
          }
        })
        setMatchedDirPaths(matched)
        // Expand only non-matched ancestors — matched dirs stay collapsed for the user to open
        setExpandedPaths(prev => {
          const next = new Set(prev)
          toExpand.forEach(p => { if (!matched.has(p)) next.add(p) })
          matched.forEach(p => next.delete(p)) // collapse matched dirs even if previously open
          return next
        })
        toExpand.forEach(p => {
          if (!matched.has(p) && hosts.some(h => !cacheRef.current.has(`${h.host}:${p}`))) {
            fetchPath(p, hosts)
          }
        })
      })
      .catch(() => setMatchedDirPaths(new Set()))
  }, [debouncedDirQuery, hosts, fetchPath])

  // Fetch currentPath whenever it, hosts, or lsFetchKey changes
  useEffect(() => {
    if (hosts.length > 0) {
      fetchPath(currentPath, hosts)
    }
  }, [currentPath, hosts, fetchPath, lsFetchKey])

  // ── Navigate to a path ───────────────────────────────────────────────────
  const navigate = useCallback((path) => {
    setCurrentPath(path)
    setExpandedPaths(new Set())
    setFilenameQuery('')
    setCategoryFilter(new Set())
    setPinnedResults(null)
  }, [])

  // ── Reset all filters / selections ───────────────────────────────────────
  const reset = useCallback(() => {
    setFilenameQuery('')
    setHashQuery('')
    setDirQuery('')
    setMatchedDirPaths(new Set())
    setCategoryFilter(new Set())
    setMinDupSize(0)
    setOnlyDups(false)
    setPinnedResults(null)
    setSelectedHosts(new Set(hosts.map(h => h.host)))
    setExpandedPaths(new Set())
  }, [hosts])

  // ── Toggle dir expansion ─────────────────────────────────────────────────
  const toggleDir = useCallback((fullPath) => {
    setExpandedPaths(prev => {
      const next = new Set(prev)
      if (next.has(fullPath)) {
        for (const p of next) {
          if (p === fullPath || p.startsWith(fullPath + '/')) next.delete(p)
        }
      } else {
        next.add(fullPath)
        fetchPath(fullPath, hosts)
      }
      return next
    })
  }, [hosts, fetchPath])

  // ── Handle sort column click (fixed: no nested setState) ─────────────────
  const handleSort = useCallback((col) => {
    if (col === sortBy) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(col)
      setSortDir('asc')
    }
  }, [sortBy])

  // ── Handle file click → zoom to all copies ────────────────────────────────
  const handleFileClick = useCallback(async (entry) => {
    if (entry.hash) {
      setHighlightedPaths(new Set([(entry.path_display || '').toLowerCase()]))
      try {
        const data = await api.files({ hash: entry.hash, limit: 500 })
        setPinnedResults(data)
      } catch {
        setPinnedResults([{
          host: entry.presentHosts?.[0] || '',
          drive: '',
          path_display: entry.path_display || '',
          filename: entry.filename || entry.segment_display || entry.segment,
          ext: '',
          file_category: entry.file_category || '',
          size_bytes: entry.size_bytes,
          hash: entry.hash,
          mtime: entry.mtime,
          last_seen_at: entry.last_seen_at,
          other_hosts: entry.other_hosts,
        }])
      }
    }
  }, [])

  // ── Handle dir copy-path button → copy path to clipboard ─────────────────
  const handleCopyPath = useCallback((displayPath) => {
    const success = () => {
      setClipboardToast(true)
      setTimeout(() => setClipboardToast(false), 2000)
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(displayPath).then(success).catch(() => {})
    } else {
      // Fallback for HTTP (non-secure context)
      const ta = document.createElement('textarea')
      ta.value = displayPath
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      try { document.execCommand('copy'); success() } catch (_) {}
      document.body.removeChild(ta)
    }
  }, [])

  // ── Handle "1 extra copy" click → find dup hash and open hash overlay ──────
  const handleDupHashClick = useCallback(async (fullPath, entry) => {
    const host = entry.presentHosts?.[0]
    if (!host) return
    try {
      const result = await api.dupHash(fullPath, host)
      if (result?.hash) {
        // Find the specific files in this subtree with that hash so we can highlight them
        const inDir = await api.files({ hash: result.hash, path_prefix: fullPath, host, limit: 50 })
        setHighlightedPaths(new Set(inDir.map(f => (f.path_display || '').toLowerCase())))
        setHashQuery(result.hash)
      }
    } catch (_) {}
  }, [])

  // ── Handle type badge click → toggle category filter ─────────────────────
  const handleTypeClick = useCallback((category) => {
    setCategoryFilter(prev => {
      const next = new Set(prev)
      if (next.has(category)) next.delete(category)
      else next.add(category)
      return next
    })
  }, [])

  // ── Build flat row list from cache (tree mode) ────────────────────────────
  const buildRows = useCallback((parentPath, depth, parentDisplayPath = parentPath) => {
    const hostDataMap = new Map()
    hosts.forEach(h => {
      const key = `${h.host}:${parentPath}`
      if (cacheRef.current.has(key)) {
        hostDataMap.set(h.host, cacheRef.current.get(key))
      }
    })

    const entries = mergeEntries(hostDataMap, selectedHosts)
    const sorted = sortEntries(entries, sortBy, sortDir)
    const rows = []

    for (const entry of sorted) {
      const fullPath = joinPath(parentPath, entry.segment)
      const fullDisplayPath = joinPath(parentDisplayPath, entry.segment_display || entry.segment)
      rows.push({ entry, parentPath, fullPath, fullDisplayPath, depth })
      if (entry.entry_type === 'dir' && expandedPaths.has(fullPath)) {
        rows.push(...buildRows(fullPath, depth + 1, fullDisplayPath))
      }
    }

    return rows
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hosts, selectedHosts, sortBy, sortDir, expandedPaths, cacheVersion])

  // ── Active results: pinned > filename > hash ──────────────────────────────
  const activeResults = pinnedResults ?? filenameResults ?? hashResults
  const isSearchMode = activeResults !== null

  // Clear highlighted paths whenever the results overlay closes
  useEffect(() => {
    if (activeResults === null) setHighlightedPaths(new Set())
  }, [activeResults])

  // ── Search result rows ────────────────────────────────────────────────────
  const searchRows = useMemo(() => {
    if (!activeResults) return null
    const converted = activeResults.map(fe => fileEntryToRow(fe))
    let filtered = categoryFilter.size > 0
      ? converted.filter(r => categoryFilter.has(r.entry.file_category))
      : converted
    if (minDupSize > 0) {
      filtered = filtered.filter(r => {
        const isDup = r.entry.dup_count > 0 || (r.entry.presentHosts?.length ?? 0) > 1
        if (!isDup) return true
        return (r.entry.size_bytes || 0) >= minDupSize
      })
    }
    if (onlyDups) {
      filtered = filtered.filter(r =>
        r.entry.dup_count > 0 || (r.entry.presentHosts?.length ?? 0) > 1
      )
    }
    return sortFileEntries(filtered, sortBy, sortDir)
  }, [activeResults, categoryFilter, minDupSize, onlyDups, sortBy, sortDir])

  // ── Unfiltered tree rows — used for available categories so the type picker
  //    doesn't collapse while multi-selecting ───────────────────────────────
  const allTreeRows = useMemo(() => buildRows(currentPath, 0), [buildRows, currentPath])

  // ── Tree rows ─────────────────────────────────────────────────────────────
  const treeRows = useMemo(() => {
    const r = allTreeRows
    let filtered = categoryFilter.size > 0
      ? r.filter(row => row.entry.entry_type === 'file' && categoryFilter.has(row.entry.file_category))
      : r
    if (minDupSize > 0) {
      filtered = filtered.filter(row => {
        if (row.entry.entry_type !== 'file') return true
        const isDup = row.entry.dup_count > 0 || (row.entry.presentHosts?.length ?? 0) > 1
        if (!isDup) return true
        return (row.entry.size_bytes || 0) >= minDupSize
      })
    }
    if (onlyDups) {
      // Strict pass: dirs with extraCopies>0, files with dup_count>0.
      const strictFiltered = filtered.filter(row => {
        if (row.entry.entry_type === 'dir') {
          return Math.max(0, (row.entry.dup_count || 0) - (row.entry.dup_hash_count || 0)) > 0
        }
        return row.entry.dup_count > 0 || (row.entry.presentHosts?.length ?? 0) > 1
      })

      // Find dirs that are expanded, have extraCopies>0, but have NO children surviving
      // the strict filter. This happens when the duplicate is split across two sibling
      // subdirectories — neither sibling has its own extraCopies but together they create
      // the parent's. We need to let the user navigate into those dirs.
      const strictChildPaths = new Set(strictFiltered.map(r => r.parentPath))
      const emptyExpandedDirs = new Set()
      strictFiltered.forEach(row => {
        if (
          row.entry.entry_type === 'dir' &&
          expandedPaths.has(row.fullPath) &&
          Math.max(0, (row.entry.dup_count || 0) - (row.entry.dup_hash_count || 0)) > 0 &&
          !strictChildPaths.has(row.fullPath)
        ) {
          emptyExpandedDirs.add(row.fullPath)
        }
      })

      if (emptyExpandedDirs.size === 0) {
        filtered = strictFiltered
      } else {
        const strictSet = new Set(strictFiltered)
        filtered = filtered.filter(row => {
          if (strictSet.has(row)) return true
          if (row.entry.entry_type === 'dir' && emptyExpandedDirs.has(row.parentPath)) {
            return (row.entry.dup_count || 0) > 0
          }
          return false
        })
      }
    }
    return filtered
  }, [allTreeRows, categoryFilter, minDupSize, onlyDups, expandedPaths])

  // ── Rows: search overlay > dir-search path-chain filter > plain tree ──────
  const rows = useMemo(() => {
    if (isSearchMode) return searchRows ?? []

    // Dir search active: filter tree to only show the path chain to each matched dir
    if (matchedDirPaths.size > 0 && debouncedDirQuery.length >= 2) {
      // Build set of all paths that should remain visible (matches + their ancestors)
      const visiblePaths = new Set()
      matchedDirPaths.forEach(p => {
        visiblePaths.add(p)
        const parts = p.split('/').filter(Boolean)
        for (let i = 1; i < parts.length; i++) {
          visiblePaths.add('/' + parts.slice(0, i).join('/'))
        }
      })
      // Show ancestors+matches, plus children of any expanded matched dir
      return treeRows.filter(row =>
        visiblePaths.has(row.fullPath) || matchedDirPaths.has(row.parentPath)
      )
    }

    return treeRows
  }, [isSearchMode, searchRows, treeRows, matchedDirPaths, debouncedDirQuery])

  // ── Available categories — from unfiltered source so multi-select works ──
  const availableCategories = useMemo(() => {
    const source = isSearchMode
      ? (activeResults ? activeResults.map(fe => fileEntryToRow(fe)) : [])
      : allTreeRows
    const cats = new Set()
    source.forEach(r => {
      if (r.entry.entry_type === 'file' && r.entry.file_category) {
        cats.add(r.entry.file_category)
      }
    })
    return [...cats].sort()
  }, [isSearchMode, activeResults, allTreeRows])

  // ── Search banner ─────────────────────────────────────────────────────────
  const searchBanner = useMemo(() => {
    if (pinnedResults !== null) return {
      label: 'all copies of file',
      clear: () => setPinnedResults(null),
    }
    if (filenameResults !== null) return {
      label: `filename: "${filenameQuery}"`,
      clear: () => { setFilenameQuery('') },
    }
    if (hashResults !== null) return {
      label: `hash: ${hashQuery}`,
      clear: () => { setHashQuery('') },
    }
    return null
  }, [pinnedResults, filenameResults, filenameQuery, hashResults, hashQuery])

  const isLoading = loadingPaths.has(currentPath)

  return (
    <div className="min-h-screen bg-slate-50">
      <Header
        hosts={hosts}
        selectedHosts={selectedHosts}
        setSelectedHosts={setSelectedHosts}
        hostColorMap={hostColorMap}
        dirQuery={dirQuery}
        setDirQuery={setDirQuery}
        filenameQuery={filenameQuery}
        setFilenameQuery={setFilenameQuery}
        hashQuery={hashQuery}
        setHashQuery={setHashQuery}
        categoryFilter={categoryFilter}
        setCategoryFilter={setCategoryFilter}
        availableCategories={availableCategories}
        minDupSize={minDupSize}
        setMinDupSize={setMinDupSize}
        onlyDups={onlyDups}
        setOnlyDups={setOnlyDups}
        visibleColumns={visibleColumns}
        setVisibleColumns={setVisibleColumns}
        onReset={reset}
      />

      <div className="max-w-screen-2xl mx-auto px-4">
        {/* Back banner — shown in search / pinned mode */}
        {searchBanner && (
          <div className="flex items-center gap-2 py-2 text-[12px]">
            <button
              onClick={searchBanner.clear}
              className="px-2 py-0.5 text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded transition-colors font-medium shrink-0"
            >
              ← Back
            </button>
            <span className="text-slate-400">Showing:</span>
            <span className="font-medium text-slate-700">{searchBanner.label}</span>
            <span className="text-slate-400">— {rows.length} result{rows.length !== 1 ? 's' : ''}</span>
          </div>
        )}

        <StatsBar stats={stats} rowCount={rows.length} isFiltered={minDupSize > 0 || categoryFilter.size > 0} />

        <FileTable
          rows={rows}
          hostColorMap={hostColorMap}
          visibleColumns={visibleColumns}
          columnOrder={columnOrder}
          sortBy={sortBy}
          sortDir={sortDir}
          onSort={handleSort}
          onToggleDir={toggleDir}
          onFileClick={handleFileClick}
          onCopyPath={handleCopyPath}
          onTypeClick={handleTypeClick}
          onDupHashClick={handleDupHashClick}
          highlightedPaths={highlightedPaths}
          matchedDirPaths={matchedDirPaths}
          expandedPaths={expandedPaths}
          isLoading={isLoading && !isSearchMode}
          filterActive={isSearchMode}
        />
      </div>

      {/* Clipboard toast */}
      {clipboardToast && (
        <div className="fixed bottom-4 right-4 z-50 bg-slate-800 text-white text-sm px-4 py-2 rounded-lg shadow-lg transition-opacity">
          Path copied to clipboard
        </div>
      )}
    </div>
  )
}
