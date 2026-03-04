import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { api } from './api.js'
import { joinPath, mergeEntries, sortEntries, hostColor, fileEntryToRow, sortFileEntries, logPerf, formatClipboardPath, hasSelectedOtherHost, shouldApplyOnlyDupsInSearch } from './utils.js'
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
  const [activeDrive, setActiveDrive] = useState('')  // '' for Mac/Linux, 'C' or 'D' for Windows

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
  const [subtreeDupPath, setSubtreeDupPath] = useState(null)          // string | null — path for subtree dup overlay
  const [pinnedSourcePath, setPinnedSourcePath] = useState(null)      // string | null — clicked file's display path (lowercase)
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
  const [structureVersion, setStructureVersion] = useState(0)   // new children loaded
  const [metadataVersion, setMetadataVersion] = useState(0)    // dup metrics merged
  const [lsFetchKey, setLsFetchKey] = useState(0)
  const minDupSizeRef = useRef(minDupSize)
  const [dupAutoExpanded, setDupAutoExpanded] = useState(new Map())  // Map<rootPath, Set<autoExpandedPaths>>
  const onlyDupsRef = useRef(onlyDups)
  const appStartRef = useRef(performance.now())
  const firstTreePaintLoggedRef = useRef(false)
  const pendingExpandRef = useRef(new Map())
  const dupMetricSegmentsRef = useRef(new Map())
  const dupMetricsInFlightRef = useRef(new Set())
  const treePageStateRef = useRef(new Map())
  const emptyPathByHostRef = useRef(new Map())
  const onlyDupsPrevRef = useRef(false)
  const [paginationVersion, setPaginationVersion] = useState(0)

  // ── Stats ───────────────────────────────────────────────────────────────
  const [stats, setStats] = useState(null)
  const [statsEnabled, setStatsEnabled] = useState(false)

  // ── Loading ─────────────────────────────────────────────────────────────
  const [loadingPaths, setLoadingPaths] = useState(new Set())

  // ── Host color map ──────────────────────────────────────────────────────
  const hostColorMap = useMemo(() => {
    const m = new Map()
    hosts.forEach((h, i) => m.set(h.host, hostColor(i)))
    return m
  }, [hosts])

  const activeHosts = useMemo(
    () => hosts.filter(h => selectedHosts.has(h.host)),
    [hosts, selectedHosts],
  )

  // ── Drive helpers ───────────────────────────────────────────────────────
  // For a host, determine the effective drive letter to use in API calls.
  // - No drives (Mac/Linux): ''
  // - Single drive: that drive letter (transparent, no drive node in tree)
  // - Multi-drive: activeDrive (set when user expands a drive node)
  const hostDrive = useCallback((host) => {
    const h = hosts.find(x => x.host === host)
    if (!h || !h.drives || h.drives.length === 0) return ''
    if (h.drives.length === 1) return h.drives[0]
    return activeDrive
  }, [hosts, activeDrive])

  // True if any selected host has multiple drives
  const hasMultiDriveHost = useMemo(() =>
    activeHosts.some(h => h.drives && h.drives.length > 1),
    [activeHosts],
  )

  // ── Debounce dir + filename queries ─────────────────────────────────────
  useEffect(() => {
    const t = setTimeout(() => setDebouncedDirQuery(dirQuery), 350)
    return () => clearTimeout(t)
  }, [dirQuery])

  useEffect(() => {
    const t = setTimeout(() => setDebouncedFilenameQuery(filenameQuery), 350)
    return () => clearTimeout(t)
  }, [filenameQuery])

  // ── Filename search (server-side) ────────────────────────────────────────
  useEffect(() => {
    if (debouncedFilenameQuery.length >= 2) {
      const controller = new AbortController()
      const started = performance.now()
      api.files({ iname: `*${debouncedFilenameQuery}*`, limit: 500, lite: 1 }, { signal: controller.signal })
        .then(data => {
          logPerf('search.filename', {
            query_len: debouncedFilenameQuery.length,
            ms: (performance.now() - started).toFixed(1),
            rows: Array.isArray(data) ? data.length : 0,
          })
          setFilenameResults(data)
        })
        .catch((err) => {
          if (err?.name === 'AbortError') return
          setFilenameResults([])
        })
      return () => controller.abort()
    } else {
      setFilenameResults(null)
    }
  }, [debouncedFilenameQuery])

  // ── Hash search ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (hashQuery.length >= 4) {
      const controller = new AbortController()
      const started = performance.now()
      api.files({ hash: hashQuery, limit: 500, lite: 1 }, { signal: controller.signal })
        .then(data => {
          logPerf('search.hash', {
            query_len: hashQuery.length,
            ms: (performance.now() - started).toFixed(1),
            rows: Array.isArray(data) ? data.length : 0,
          })
          setHashResults(data)
        })
        .catch((err) => {
          if (err?.name === 'AbortError') return
          setHashResults([])
        })
      return () => controller.abort()
    } else {
      setHashResults(null)
    }
  }, [hashQuery])

  // Enable stats fetch after the first tree path has loaded.
  useEffect(() => {
    if (statsEnabled) return
    if (hosts.length === 0) return
    if (loadingPaths.has(currentPath)) return
    setStatsEnabled(true)
  }, [statsEnabled, hosts.length, loadingPaths, currentPath])

  // ── Initial load ─────────────────────────────────────────────────────────
  useEffect(() => {
    Promise.all([
      api.hosts(),
      api.clientHost().catch(() => ({ client_host: null })),
    ])
      .then(([data, client]) => {
        setHosts(data)
        const clientHost = (client?.client_host || '').toLowerCase()
        const matched = clientHost
          ? data.find(h => h.host.toLowerCase() === clientHost)
          : null
        setSelectedHosts(
          matched
            ? new Set([matched.host])
            : new Set(data.map(h => h.host)),
        )
      })
      .catch(() => {})
  }, [])

  // ── Periodic host refresh (scanning state, stats) ───────────────────────
  useEffect(() => {
    const id = setInterval(() => {
      api.hosts().then(data => setHosts(data)).catch(() => {})
    }, 60000)
    return () => clearInterval(id)
  }, [])

  // ── Stats (re-fetched when minDupSize, categoryFilter, or selectedHosts changes)
  useEffect(() => {
    if (!statsEnabled) return
    const params = { min_size: minDupSize }
    if (categoryFilter.size > 0) params.categories = [...categoryFilter].join(',')
    if (selectedHosts.size > 0 && selectedHosts.size < hosts.length) {
      params.hosts = [...selectedHosts].join(',')
    }
    api.stats(params)
      .then(setStats)
      .catch(() => {})
  }, [statsEnabled, minDupSize, categoryFilter, selectedHosts, hosts.length])

  // ── Sync onlyDupsRef + clear auto-expanded on toggle off ──────────────
  useEffect(() => {
    onlyDupsRef.current = onlyDups
    if (!onlyDups) setDupAutoExpanded(new Map())
  }, [onlyDups])

  // ── effectiveExpanded: manual + auto-expanded paths ──────────────────────
  const effectiveExpanded = useMemo(() => {
    if (dupAutoExpanded.size === 0) return expandedPaths
    const union = new Set(expandedPaths)
    for (const paths of dupAutoExpanded.values()) {
      for (const p of paths) union.add(p)
    }
    return union
  }, [expandedPaths, dupAutoExpanded])

  // ── When minDupSize changes, bust the ls cache so dup counts refresh ──────
  useEffect(() => {
    minDupSizeRef.current = minDupSize
    cacheRef.current.clear()
    dupMetricSegmentsRef.current.clear()
    dupMetricsInFlightRef.current.clear()
    treePageStateRef.current.clear()
    setPaginationVersion(v => v + 1)
    setExpandedPaths(new Set())
    setDupAutoExpanded(new Map())
    setLsFetchKey(k => k + 1)
  }, [minDupSize])

  // ── Fetch ls data for a path (all hosts) ─────────────────────────────────
  const fetchPath = useCallback(async (path, hostList, opts = {}) => {
    const loadMore = Boolean(opts.loadMore)
    const enrichDupMetrics = Boolean(opts.enrichDupMetrics)
    const forceDrive = opts.drive  // optional explicit drive override

    const hasEmptyAncestor = (host, drive, fullPath) => {
      const empties = emptyPathByHostRef.current.get(`${host}:${drive}`)
      if (!empties || empties.size === 0) return false
      if (fullPath === '/') return false
      const parts = fullPath.split('/').filter(Boolean)
      for (let i = 1; i <= parts.length; i++) {
        const p = '/' + parts.slice(0, i).join('/')
        if (empties.has(p)) return true
      }
      return false
    }

    const toFetch = hostList.filter(h => {
      const drive = forceDrive !== undefined ? forceDrive : hostDrive(h.host)
      const key = `${h.host}:${drive}:${path}`
      if (!loadMore) return !cacheRef.current.has(key) && !hasEmptyAncestor(h.host, drive, path)
      const pageState = treePageStateRef.current.get(key)
      return Boolean(pageState?.hasMore)
    })
    if (toFetch.length > 0) {
      setLoadingPaths(prev => new Set([...prev, path]))

      await Promise.all(toFetch.map(async h => {
        const drive = forceDrive !== undefined ? forceDrive : hostDrive(h.host)
        const key = `${h.host}:${drive}:${path}`
        const pageState = treePageStateRef.current.get(key)
        try {
          const data = await api.treeChildren(
            path,
            h.host,
            loadMore ? { cursor: pageState?.nextCursor } : {},
            drive,
          )
          const items = Array.isArray(data?.items) ? data.items : []
          if (loadMore) {
            const existing = cacheRef.current.get(key) || []
            const seen = new Set(existing.map(e => e.segment))
            const merged = [...existing]
            items.forEach(item => {
              if (!seen.has(item.segment)) merged.push(item)
            })
            cacheRef.current.set(key, merged)
          } else {
            cacheRef.current.set(key, items)
          }
          if (!loadMore && items.length === 0 && !Boolean(data?.has_more)) {
            const emptyKey = `${h.host}:${drive}`
            const empties = emptyPathByHostRef.current.get(emptyKey) || new Set()
            empties.add(path)
            emptyPathByHostRef.current.set(emptyKey, empties)
          }
          treePageStateRef.current.set(key, {
            hasMore: Boolean(data?.has_more),
            nextCursor: data?.next_cursor || null,
          })
        } catch {
          cacheRef.current.set(key, [])
          treePageStateRef.current.set(key, { hasMore: false, nextCursor: null })
        }
      }))

      setLoadingPaths(prev => {
        const next = new Set(prev)
        next.delete(path)
        return next
      })
      setStructureVersion(v => v + 1)
      setPaginationVersion(v => v + 1)
    }

    if (!enrichDupMetrics) return

    const minAtRequest = minDupSizeRef.current
    const metricsTargets = hostList
      .map(h => {
        const drive = forceDrive !== undefined ? forceDrive : hostDrive(h.host)
        const key = `${h.host}:${drive}:${path}`
        const metricKey = `${h.host}:${drive}:${path}:${minAtRequest}`
        const entries = cacheRef.current.get(key) || []
        if (!entries.length) return null
        if (dupMetricsInFlightRef.current.has(metricKey)) return null
        const loaded = dupMetricSegmentsRef.current.get(metricKey) || new Set()
        const missing = entries
          .map(e => e.segment)
          .filter(seg => seg && !loaded.has(seg))
        if (missing.length === 0) return null
        return { host: h.host, drive, key, metricKey, missing }
      })
      .filter(Boolean)

    if (metricsTargets.length === 0) return

    metricsTargets.forEach(target => {
      const { host, drive, key, metricKey, missing } = target
      dupMetricsInFlightRef.current.add(metricKey)
      api.treeDupMetrics(path, host, minAtRequest, missing, drive)
        .then(data => {
          if (minDupSizeRef.current !== minAtRequest) return
          const metrics = data?.metrics || {}
          const existing = cacheRef.current.get(key) || []
          const merged = existing.map(entry => {
            const m = metrics[entry.segment]
            if (!m) return entry
            return {
              ...entry,
              dup_count: m.dup_count ?? 0,
              dup_hash_count: m.dup_hash_count ?? 0,
              other_hosts: m.other_hosts ?? null,
              is_hard_linked: Boolean(m.is_hard_linked),
              ...(m.file_count != null ? { file_count: m.file_count } : {}),
              ...(m.total_bytes != null ? { total_bytes: m.total_bytes } : {}),
            }
          })
          cacheRef.current.set(key, merged)
          const loaded = dupMetricSegmentsRef.current.get(metricKey) || new Set()
          missing.forEach(seg => loaded.add(seg))
          dupMetricSegmentsRef.current.set(metricKey, loaded)
          setMetadataVersion(v => v + 1)
        })
        .catch(() => {})
        .finally(() => {
          dupMetricsInFlightRef.current.delete(metricKey)
        })
    })
  }, [hostDrive])

  // When dup-only mode is enabled, ensure dup metrics are loaded for the
  // currently visible paths so filtering has data to work with.
  useEffect(() => {
    if (!onlyDups) {
      onlyDupsPrevRef.current = false
      return
    }
    if (onlyDupsPrevRef.current) return
    onlyDupsPrevRef.current = true
    if (activeHosts.length === 0) return
    fetchPath(currentPath, activeHosts, { enrichDupMetrics: true })
  }, [onlyDups, currentPath, activeHosts, fetchPath])

  const hasMoreForPath = useCallback((path) => {
    for (const host of selectedHosts) {
      const drive = hostDrive(host)
      const pageState = treePageStateRef.current.get(`${host}:${drive}:${path}`)
      if (pageState?.hasMore) return true
    }
    return false
  }, [selectedHosts, hostDrive])

  const handleLoadMore = useCallback((path) => {
    fetchPath(path, activeHosts, {
      loadMore: true,
      enrichDupMetrics: true,
    })
  }, [fetchPath, activeHosts])

  // ── Fetch dup ancestor dirs for auto-expand ─────────────────────────────
  const fetchDupAncestors = useCallback(async (rootPath) => {
    if (activeHosts.length === 0) return
    // Keep dup-only interaction responsive by using a single anchor host for
    // auto-expansion paths instead of fan-out across all selected hosts.
    const anchorHost = activeHosts[0].host
    const drive = hostDrive(anchorHost)
    const results = await Promise.allSettled([
      api.dupDirAncestors(anchorHost, rootPath, minDupSizeRef.current, 500, drive),
    ])
    const allPaths = new Set()
    for (const r of results) {
      if (r.status === 'fulfilled' && Array.isArray(r.value?.paths)) {
        for (const p of r.value.paths) allPaths.add(p)
      }
    }
    if (allPaths.size === 0) return
    const capped = [...allPaths]
      .sort((a, b) => a.split('/').length - b.split('/').length)
      .slice(0, 300)
    setDupAutoExpanded(prev => {
      const next = new Map(prev)
      next.set(rootPath, new Set(capped))
      return next
    })
    // Avoid prefetching all auto-expanded descendants; load on interaction.
  }, [activeHosts, hostDrive])

  // ── Directory search → expand tree to matching dirs ─────────────────────
  // NOTE: must be after `fetchPath` useCallback to avoid TDZ
  useEffect(() => {
    if (debouncedDirQuery.length < 2) {
      setMatchedDirPaths(new Set())
      return
    }
    const controller = new AbortController()
    const started = performance.now()
    api.directories(debouncedDirQuery, 10, { signal: controller.signal })
      .then(dirs => {
        logPerf('search.directory', {
          query_len: debouncedDirQuery.length,
          ms: (performance.now() - started).toFixed(1),
          rows: Array.isArray(dirs) ? dirs.length : 0,
        })
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
          if (!matched.has(p) && activeHosts.some(h => !cacheRef.current.has(`${h.host}:${hostDrive(h.host)}:${p}`))) {
            fetchPath(p, activeHosts, { enrichDupMetrics: false })
          }
        })
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return
        setMatchedDirPaths(new Set())
      })
    return () => controller.abort()
  }, [debouncedDirQuery, activeHosts, fetchPath, hostDrive])

  // Fetch currentPath whenever it, hosts, or lsFetchKey changes.
  // Always enrich dup metrics — with aggregate tables the call is fast,
  // and having dup data pre-loaded makes dup-only toggle instant.
  useEffect(() => {
    if (hosts.length > 0) {
      fetchPath(currentPath, activeHosts, { enrichDupMetrics: true })
    }
  }, [currentPath, hosts, activeHosts, fetchPath, lsFetchKey])

  // Pre-fetch drive roots so synthetic drive nodes show aggregated subtotals
  useEffect(() => {
    if (!hasMultiDriveHost || currentPath !== '/') return
    const seen = new Set()
    activeHosts.forEach(h => {
      if (h.drives && h.drives.length > 1) {
        h.drives.forEach(d => {
          if (seen.has(d)) return
          seen.add(d)
          const driveHosts = activeHosts.filter(x => x.drives && x.drives.includes(d))
          fetchPath('/', driveHosts, { enrichDupMetrics: true, drive: d })
        })
      }
    })
  }, [hasMultiDriveHost, currentPath, activeHosts, fetchPath, lsFetchKey])

  // ── Navigate to a path ───────────────────────────────────────────────────
  const navigate = useCallback((path, drive) => {
    setCurrentPath(path)
    if (drive !== undefined) setActiveDrive(drive)
    setExpandedPaths(new Set())
    setDupAutoExpanded(new Map())
    setFilenameQuery('')
    setCategoryFilter(new Set())
    setPinnedResults(null)
    setPinnedSourcePath(null)
    setSubtreeDupPath(null)
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
    setPinnedSourcePath(null)
    setSubtreeDupPath(null)
    setSelectedHosts(new Set(hosts.map(h => h.host)))
    setExpandedPaths(new Set())
    setDupAutoExpanded(new Map())
    setActiveDrive('')
  }, [hosts])

  // ── Toggle dir expansion ─────────────────────────────────────────────────
  const toggleDir = useCallback((fullPath, entry) => {
    const isCurrentlyExpanded = effectiveExpanded.has(fullPath)
    if (isCurrentlyExpanded) {
      // Collapse manual expandedPaths
      setExpandedPaths(prev => {
        const next = new Set(prev)
        for (const p of next) {
          if (p === fullPath || p.startsWith(fullPath + '/')) next.delete(p)
        }
        // Also handle drive node collapse
        if (fullPath.startsWith('__drive__:')) {
          next.delete(fullPath)
        }
        return next
      })
      // Collapse auto-expanded: remove entry for this root + descendants from other roots
      setDupAutoExpanded(prev => {
        const next = new Map(prev)
        next.delete(fullPath)
        for (const [root, paths] of next) {
          const filtered = new Set()
          for (const p of paths) {
            if (p !== fullPath && !p.startsWith(fullPath + '/')) filtered.add(p)
          }
          if (filtered.size !== paths.size) {
            if (filtered.size === 0) next.delete(root)
            else next.set(root, filtered)
          }
        }
        return next
      })
    } else {
      // Drive node expansion
      if (fullPath.startsWith('__drive__:')) {
        const driveLabel = fullPath.split(':')[1]
        setActiveDrive(driveLabel)
        pendingExpandRef.current.set(fullPath, performance.now())
        setExpandedPaths(prev => new Set([...prev, fullPath]))
        // Fetch root path for this drive
        const driveHosts = activeHosts.filter(h => h.drives && h.drives.includes(driveLabel))
        fetchPath('/', driveHosts, { enrichDupMetrics: true, drive: driveLabel })
        return
      }
      // Normal expand
      pendingExpandRef.current.set(fullPath, performance.now())
      setExpandedPaths(prev => new Set([...prev, fullPath]))
      // Determine drive context from entry if available
      const driveCtx = entry?.driveContext || (entry?.isDriveNode ? entry.driveLabel : undefined)
      fetchPath(fullPath, activeHosts, { enrichDupMetrics: true, drive: driveCtx })
      // Auto-expand if onlyDups is active
      if (onlyDupsRef.current) fetchDupAncestors(fullPath)
    }
  }, [effectiveExpanded, activeHosts, fetchPath, fetchDupAncestors])

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
  const handleFileClick = useCallback(async (entry, treeDisplayPath) => {
    if (entry.hash) {
      const displayPath = treeDisplayPath || entry.path_display || ''
      const srcPath = displayPath.toLowerCase()
      setHighlightedPaths(new Set([srcPath]))
      setPinnedSourcePath(srcPath)
      try {
        const data = await api.files({ hash: entry.hash, limit: 500, lite: 1 })
        setPinnedResults(data)
      } catch {
        setPinnedResults([{
          host: entry.presentHosts?.[0] || '',
          drive: '',
          path_display: displayPath,
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
  const handleCopyPath = useCallback((displayPath, driveCtx) => {
    const drive = driveCtx || ''
    const quoted = formatClipboardPath(displayPath, drive)
    const success = () => {
      setClipboardToast(true)
      setTimeout(() => setClipboardToast(false), 2000)
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(quoted).then(success).catch(() => {})
    } else {
      // Fallback for HTTP (non-secure context)
      const ta = document.createElement('textarea')
      ta.value = quoted
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      try {
        if (document.execCommand('copy')) success()
      } catch (_) {}
      document.body.removeChild(ta)
    }
  }, [])

  // ── Handle "1 extra copy" click → find dup hash and open hash overlay ──────
  const handleDupHashClick = useCallback(async (fullPath, entry) => {
    const host = entry.presentHosts?.[0]
    if (!host) return
    const drive = hostDrive(host)
    try {
      const result = await api.dupHash(fullPath, host, minDupSizeRef.current, drive)
      if (result?.hash) {
        // Find the specific files in this subtree with that hash so we can highlight them
        const inDir = await api.files({ hash: result.hash, path_prefix: fullPath, host, limit: 50, lite: 1 })
        setHighlightedPaths(new Set(inDir.map(f => (f.path_display || '').toLowerCase())))
        setHashQuery(result.hash)
      }
    } catch (_) {}
  }, [hostDrive])

  // ── Handle subtree dup arrow → show all dups in subtree grouped by hash ──
  const handleDupSubtreeClick = useCallback(async (fullPath, entry) => {
    const host = entry.presentHosts?.[0]
    if (!host) return
    const drive = hostDrive(host)
    try {
      const data = await api.subtreeDups(host, fullPath, minDupSizeRef.current, 1000, drive)
      setHighlightedPaths(new Set())
      setSubtreeDupPath(fullPath)
      setPinnedResults(data)
    } catch (_) {}
  }, [hostDrive])

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
    // At root path for multi-drive hosts, inject synthetic drive entries
    if (parentPath === '/' && depth === 0 && hasMultiDriveHost) {
      const rows = []
      // Collect drives from all active hosts
      const allDrives = new Set()
      activeHosts.forEach(h => {
        if (h.drives && h.drives.length > 1) {
          h.drives.forEach(d => allDrives.add(d))
        }
      })

      // For hosts without drives (Mac/Linux), show their normal tree
      const noDriveHosts = activeHosts.filter(h => !h.drives || h.drives.length <= 1)
      if (noDriveHosts.length > 0) {
        const hostDataMap = new Map()
        noDriveHosts.forEach(h => {
          const drive = h.drives && h.drives.length === 1 ? h.drives[0] : ''
          const key = `${h.host}:${drive}:${parentPath}`
          if (cacheRef.current.has(key)) {
            hostDataMap.set(h.host, cacheRef.current.get(key))
          }
        })
        const entries = mergeEntries(hostDataMap, selectedHosts)
        const sorted = sortEntries(entries, sortBy, sortDir)
        for (const entry of sorted) {
          const fullPath = joinPath(parentPath, entry.segment)
          const fullDisplayPath = joinPath(parentDisplayPath, entry.segment_display || entry.segment)
          rows.push({ entry, parentPath, fullPath, fullDisplayPath, depth })
          if (entry.entry_type === 'dir' && effectiveExpanded.has(fullPath)) {
            rows.push(...buildRows(fullPath, depth + 1, fullDisplayPath))
          }
        }
      }

      // Add synthetic drive entries for multi-drive hosts
      for (const d of [...allDrives].sort()) {
        const drivePath = `__drive__:${d}`
        const driveEntry = {
          segment: `${d}:`,
          segment_display: `${d}:`,
          entry_type: 'dir',
          file_count: 0,
          total_bytes: null,
          dup_count: 0,
          dup_hash_count: 0,
          isDriveNode: true,
          driveLabel: d,
        }
        // Aggregate totals from cached children for this drive
        activeHosts.forEach(h => {
          if (h.drives && h.drives.includes(d)) {
            const key = `${h.host}:${d}:/`
            const entries = cacheRef.current.get(key)
            if (entries) {
              for (const e of entries) {
                if (e.total_bytes != null) driveEntry.total_bytes = (driveEntry.total_bytes || 0) + e.total_bytes
                if (e.file_count != null) driveEntry.file_count = (driveEntry.file_count || 0) + e.file_count
                driveEntry.dup_count += e.dup_count || 0
                driveEntry.dup_hash_count += e.dup_hash_count || 0
              }
            }
          }
        })
        driveEntry.presentHosts = activeHosts
          .filter(h => h.drives && h.drives.includes(d))
          .map(h => h.host)
        rows.push({ entry: driveEntry, parentPath: '/', fullPath: drivePath, fullDisplayPath: `${d}:`, depth: 0 })
        if (effectiveExpanded.has(drivePath)) {
          // When a drive is expanded, show its root children
          const hostDataMap = new Map()
          activeHosts.forEach(h => {
            if (h.drives && h.drives.includes(d)) {
              const key = `${h.host}:${d}:/`
              if (cacheRef.current.has(key)) {
                hostDataMap.set(h.host, cacheRef.current.get(key))
              }
            }
          })
          const entries = mergeEntries(hostDataMap, selectedHosts)
          const sorted = sortEntries(entries, sortBy, sortDir)
          for (const entry of sorted) {
            const fullPath = joinPath('/', entry.segment)
            const fullDisplayPath = joinPath(`${d}:`, entry.segment_display || entry.segment)
            rows.push({ entry, parentPath: drivePath, fullPath, fullDisplayPath, depth: 1, driveContext: d })
            if (entry.entry_type === 'dir' && effectiveExpanded.has(fullPath)) {
              rows.push(...buildRowsForDrive(fullPath, 2, fullDisplayPath, d))
            }
          }
        }
      }
      return rows
    }

    const hostDataMap = new Map()
    hosts.forEach(h => {
      const drive = hostDrive(h.host)
      const key = `${h.host}:${drive}:${parentPath}`
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
      if (entry.entry_type === 'dir' && effectiveExpanded.has(fullPath)) {
        rows.push(...buildRows(fullPath, depth + 1, fullDisplayPath))
      }
    }

    return rows
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hosts, selectedHosts, activeHosts, sortBy, sortDir, effectiveExpanded, structureVersion, metadataVersion, hasMultiDriveHost, hostDrive])

  // Helper for building rows within a specific drive context
  const buildRowsForDrive = useCallback((parentPath, depth, parentDisplayPath, drive) => {
    const hostDataMap = new Map()
    activeHosts.forEach(h => {
      if (h.drives && h.drives.includes(drive)) {
        const key = `${h.host}:${drive}:${parentPath}`
        if (cacheRef.current.has(key)) {
          hostDataMap.set(h.host, cacheRef.current.get(key))
        }
      }
    })

    const entries = mergeEntries(hostDataMap, selectedHosts)
    const sorted = sortEntries(entries, sortBy, sortDir)
    const rows = []

    for (const entry of sorted) {
      const fullPath = joinPath(parentPath, entry.segment)
      const fullDisplayPath = joinPath(parentDisplayPath, entry.segment_display || entry.segment)
      rows.push({ entry, parentPath, fullPath, fullDisplayPath, depth, driveContext: drive })
      if (entry.entry_type === 'dir' && effectiveExpanded.has(fullPath)) {
        rows.push(...buildRowsForDrive(fullPath, depth + 1, fullDisplayPath, drive))
      }
    }

    return rows
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeHosts, selectedHosts, sortBy, sortDir, effectiveExpanded, structureVersion, metadataVersion])

  // ── Active results: pinned > filename > hash ──────────────────────────────
  const activeResults = pinnedResults ?? filenameResults ?? hashResults
  const isSearchMode = activeResults !== null
  const isHashResultsMode = pinnedResults === null && filenameResults === null && hashResults !== null

  // Clear highlighted paths whenever the results overlay closes
  useEffect(() => {
    if (activeResults === null) setHighlightedPaths(new Set())
  }, [activeResults])

  // ── Search result rows ────────────────────────────────────────────────────
  const searchRows = useMemo(() => {
    if (!activeResults) return null
    const converted = activeResults.map(fe => fileEntryToRow(fe))
    const isPinnedCopiesMode = pinnedResults !== null && !subtreeDupPath && !!pinnedSourcePath

    // Keep search/overlay results host-scoped to current selection.
    // Without this, hash overlays can leak rows from unselected hosts.
    const hostFiltered = converted.filter(r => {
      const host = (r.entry.presentHosts && r.entry.presentHosts[0]) || ''
      return selectedHosts.has(host)
    })

    if (isPinnedCopiesMode) {
      const sourceRow = hostFiltered.find(r => (r.entry.path_display || '').toLowerCase() === pinnedSourcePath)
      const sourceBelowMinDupSize =
        sourceRow && minDupSize > 0 && (sourceRow.entry.size_bytes || 0) < minDupSize

      // If the clicked file is below min dup size, keep only that file in the copies view.
      if (sourceBelowMinDupSize) return sourceRow ? [sourceRow] : []

      // In pinned copies view above threshold, all rows share the same hash and are duplicates.
      hostFiltered.forEach(r => { r.entry.dup_count = 1 })
    }

    // In subtree dup mode, mark all rows as dups so "only dups" filter doesn't hide them
    if (subtreeDupPath) {
      hostFiltered.forEach(r => { r.entry.dup_count = 1 })
    }
    let filtered = categoryFilter.size > 0
      ? hostFiltered.filter(r => categoryFilter.has(r.entry.file_category))
      : hostFiltered
    if (minDupSize > 0) {
      filtered = filtered.filter(r => {
        const isDup = r.entry.dup_count > 0 || hasSelectedOtherHost(r.entry.other_hosts, selectedHosts)
        if (!isDup) return true
        return (r.entry.size_bytes || 0) >= minDupSize
      })
    }
    // IMPORTANT: hash-result overlays are already hash-qualified and should not
    // be re-filtered by generic "Only dups" logic. Doing so can hide valid
    // same-host duplicate click-through results (for example from "1 extra copy").
    if (shouldApplyOnlyDupsInSearch(onlyDups, { isHashResultsMode, subtreeDupPath })) {
      filtered = filtered.filter(r =>
        r.entry.dup_count > 0 || hasSelectedOtherHost(r.entry.other_hosts, selectedHosts)
      )
      // In pinned single-file mode, force-include the source file even if it has no dups
      if (pinnedResults !== null && !subtreeDupPath && pinnedSourcePath) {
        const hasSource = filtered.some(r => (r.entry.path_display || '').toLowerCase() === pinnedSourcePath)
        if (!hasSource) {
          const sourceRow = hostFiltered.find(r => (r.entry.path_display || '').toLowerCase() === pinnedSourcePath)
          if (sourceRow) filtered = [sourceRow, ...filtered]
        }
      }
    }
    // In subtree dup mode: deterministic hash→path→filename sort, ignore UI sort state
    if (subtreeDupPath) {
      const subtreeSorted = [...filtered].sort((a, b) => {
        const hA = a.entry.hash || '', hB = b.entry.hash || ''
        if (hA < hB) return -1
        if (hA > hB) return 1
        const dirA = (a.entry.path_display || '').split('/').slice(0, -1).join('/')
        const dirB = (b.entry.path_display || '').split('/').slice(0, -1).join('/')
        if (dirA < dirB) return -1
        if (dirA > dirB) return 1
        const nameA = a.entry.filename || '', nameB = b.entry.filename || ''
        if (nameA < nameB) return -1
        if (nameA > nameB) return 1
        const pathA = a.entry.path_display || '', pathB = b.entry.path_display || ''
        if (pathA < pathB) return -1
        if (pathA > pathB) return 1
        return 0
      })
      const grouped = []
      let lastHash = null
      let groupCount = 0
      let groupStartIdx = -1
      for (const row of subtreeSorted) {
        const h = row.entry.hash
        if (h !== lastHash) {
          // Backfill count on previous group header
          if (groupStartIdx >= 0) grouped[groupStartIdx].count = groupCount
          grouped.push({ isGroupHeader: true, hash: h || '?', count: 0 })
          groupStartIdx = grouped.length - 1
          groupCount = 0
          lastHash = h
        }
        grouped.push(row)
        groupCount++
      }
      if (groupStartIdx >= 0) grouped[groupStartIdx].count = groupCount
      return grouped
    }
    return sortFileEntries(filtered, sortBy, sortDir)
  }, [activeResults, isHashResultsMode, subtreeDupPath, pinnedSourcePath, categoryFilter, minDupSize, onlyDups, selectedHosts, sortBy, sortDir])

  // ── Unfiltered tree rows — used for available categories so the type picker
  //    doesn't collapse while multi-selecting.  Skip in search mode since
  //    categories come from activeResults instead.
  const allTreeRows = useMemo(
    () => isSearchMode ? [] : buildRows(currentPath, 0),
    [buildRows, currentPath, isSearchMode],
  )

  // ── Tree rows ─────────────────────────────────────────────────────────────
  const treeRows = useMemo(() => {
    const r = allTreeRows
    let filtered = categoryFilter.size > 0
      ? r.filter(row => row.entry.entry_type === 'file' && categoryFilter.has(row.entry.file_category))
      : r
    if (minDupSize > 0) {
      filtered = filtered.filter(row => {
        if (row.entry.entry_type !== 'file') return true
        const isDup = row.entry.dup_count > 0 || hasSelectedOtherHost(row.entry.other_hosts, selectedHosts)
        if (!isDup) return true
        return (row.entry.size_bytes || 0) >= minDupSize
      })
    }
    if (onlyDups) {
      // Strict pass: dirs with extraCopies>0 or cross-host dups, files with dup_count>0 or cross-host same-hash.
      const strictFiltered = filtered.filter(row => {
        if (row.entry.entry_type === 'dir') {
          const extraCopies = Math.max(0, (row.entry.dup_count || 0) - (row.entry.dup_hash_count || 0))
          return extraCopies > 0 || hasSelectedOtherHost(row.entry.other_hosts, selectedHosts)
        }
        return row.entry.dup_count > 0 || hasSelectedOtherHost(row.entry.other_hosts, selectedHosts)
      })

      // Build keep-set: strict rows + every ancestor dir up to root.
      // This ensures the tree path to any dup is always visible, even
      // through dirs whose own extraCopies is 0.
      const keepPaths = new Set()
      strictFiltered.forEach(row => {
        keepPaths.add(row.fullPath)
        const parts = row.fullPath.split('/').filter(Boolean)
        for (let i = 1; i < parts.length; i++) {
          keepPaths.add('/' + parts.slice(0, i).join('/'))
        }
      })

      // Lenient expansion: when a strict dir is expanded but has no strict
      // children (dup is split across sibling subdirs), show children with
      // dup_count > 0 so the user can navigate into the split-dup structure.
      const strictChildParents = new Set(strictFiltered.map(r => r.parentPath))
      filtered.forEach(row => {
        if (keepPaths.has(row.fullPath)) return
        if (
          row.entry.entry_type === 'dir' &&
          effectiveExpanded.has(row.parentPath) &&
          keepPaths.has(row.parentPath) &&
          !strictChildParents.has(row.parentPath) &&
          (row.entry.dup_count || 0) > 0
        ) {
          keepPaths.add(row.fullPath)
        }
      })

      filtered = filtered.filter(row => keepPaths.has(row.fullPath))
    }
    return filtered
  }, [allTreeRows, categoryFilter, minDupSize, onlyDups, selectedHosts, effectiveExpanded])

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
      const filtered = treeRows.filter(row =>
        visiblePaths.has(row.fullPath) || matchedDirPaths.has(row.parentPath)
      )
      const withMore = []
      for (let i = 0; i < filtered.length; i++) {
        const row = filtered[i]
        withMore.push(row)
        if (row.entry?.entry_type === 'dir' && effectiveExpanded.has(row.fullPath) && hasMoreForPath(row.fullPath)) {
          const next = filtered[i + 1]
          const endOfSubtree = !next || next.depth <= row.depth
          if (endOfSubtree) {
            withMore.push({
              isLoadMore: true,
              path: row.fullPath,
              fullPath: `${row.fullPath}::__more__`,
              depth: row.depth + 1,
            })
          }
        }
      }
      if (hasMoreForPath(currentPath)) {
        withMore.push({
          isLoadMore: true,
          path: currentPath,
          fullPath: `${currentPath}::__more_root__`,
          depth: 0,
        })
      }
      return withMore
    }

    const withMore = []
    for (let i = 0; i < treeRows.length; i++) {
      const row = treeRows[i]
      withMore.push(row)
      if (row.entry?.entry_type === 'dir' && effectiveExpanded.has(row.fullPath) && hasMoreForPath(row.fullPath)) {
        const next = treeRows[i + 1]
        const endOfSubtree = !next || next.depth <= row.depth
        if (endOfSubtree) {
          withMore.push({
            isLoadMore: true,
            path: row.fullPath,
            fullPath: `${row.fullPath}::__more__`,
            depth: row.depth + 1,
          })
        }
      }
    }
    if (hasMoreForPath(currentPath)) {
      withMore.push({
        isLoadMore: true,
        path: currentPath,
        fullPath: `${currentPath}::__more_root__`,
        depth: 0,
      })
    }

    return withMore
  }, [
    isSearchMode,
    searchRows,
    treeRows,
    matchedDirPaths,
    debouncedDirQuery,
    effectiveExpanded,
    hasMoreForPath,
    currentPath,
    paginationVersion,
  ])

  const isLoading = hosts.length === 0 || loadingPaths.has(currentPath)

  useEffect(() => {
    if (!firstTreePaintLoggedRef.current && hosts.length > 0 && rows.length > 0 && !isLoading && !isSearchMode) {
      firstTreePaintLoggedRef.current = true
      logPerf('ui.first_tree_paint', {
        ms: (performance.now() - appStartRef.current).toFixed(1),
        rows: rows.length,
        hosts: hosts.length,
      })
    }
  }, [hosts.length, rows.length, isLoading, isSearchMode])

  useEffect(() => {
    if (pendingExpandRef.current.size === 0) return
    for (const [path, started] of pendingExpandRef.current.entries()) {
      if (!loadingPaths.has(path)) {
        logPerf('ui.expand_path', {
          path,
          ms: (performance.now() - started).toFixed(1),
        })
        pendingExpandRef.current.delete(path)
      }
    }
  }, [loadingPaths])

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
    if (pinnedResults !== null) {
      const label = subtreeDupPath
        ? `duplicate files under ${subtreeDupPath}`
        : 'all copies of file'
      return {
        label,
        clear: () => { setPinnedResults(null); setPinnedSourcePath(null); setSubtreeDupPath(null) },
      }
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
  }, [pinnedResults, subtreeDupPath, filenameResults, filenameQuery, hashResults, hashQuery])

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
          selectedHosts={selectedHosts}
          minDupSize={minDupSize}
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
          onDupSubtreeClick={handleDupSubtreeClick}
          onLoadMore={handleLoadMore}
          highlightedPaths={highlightedPaths}
          matchedDirPaths={matchedDirPaths}
          expandedPaths={effectiveExpanded}
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
