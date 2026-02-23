// ─── Formatting ─────────────────────────────────────────────────────────────

export function formatBytes(bytes) {
  if (bytes == null) return '—'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const val = bytes / Math.pow(1024, i)
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`
}

// Both date formatters use local timezone so Modified and Last Seen are comparable
function toLocalDate(ms) {
  const d = new Date(ms)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function formatDate(unixSeconds) {
  if (unixSeconds == null) return '—'
  return toLocalDate(unixSeconds * 1000)
}

// For ISO datetime strings returned by the server (last_seen_at, last_scan_at)
export function formatISODate(isoString) {
  if (!isoString) return '—'
  return toLocalDate(new Date(isoString).getTime())
}

// ─── Path helpers ────────────────────────────────────────────────────────────

export function joinPath(parent, segment) {
  if (parent === '/') return '/' + segment
  return parent + '/' + segment
}

export function pathSegments(path) {
  if (!path || path === '/') return []
  return path.split('/').filter(Boolean)
}

// ─── Host color palette ──────────────────────────────────────────────────────

const PALETTE = [
  {
    active: 'bg-blue-600 text-white',
    inactive: 'border border-blue-300 text-blue-600 bg-white hover:bg-blue-50',
    badge: 'bg-blue-100 text-blue-700',
  },
  {
    active: 'bg-emerald-600 text-white',
    inactive: 'border border-emerald-300 text-emerald-600 bg-white hover:bg-emerald-50',
    badge: 'bg-emerald-100 text-emerald-700',
  },
  {
    active: 'bg-violet-600 text-white',
    inactive: 'border border-violet-300 text-violet-600 bg-white hover:bg-violet-50',
    badge: 'bg-violet-100 text-violet-700',
  },
  {
    active: 'bg-amber-500 text-white',
    inactive: 'border border-amber-300 text-amber-600 bg-white hover:bg-amber-50',
    badge: 'bg-amber-100 text-amber-700',
  },
  {
    active: 'bg-rose-600 text-white',
    inactive: 'border border-rose-300 text-rose-600 bg-white hover:bg-rose-50',
    badge: 'bg-rose-100 text-rose-700',
  },
]

export function hostColor(index) {
  return PALETTE[index % PALETTE.length]
}

// ─── Data merging ────────────────────────────────────────────────────────────

/**
 * Merge per-host LsEntry arrays into a single list.
 * hostDataMap: Map<hostName, LsEntry[]>
 * selectedHosts: Set<hostName>
 */
export function mergeEntries(hostDataMap, selectedHosts) {
  const bySegment = new Map()

  for (const host of selectedHosts) {
    const entries = hostDataMap.get(host) || []
    for (const entry of entries) {
      if (!bySegment.has(entry.segment)) {
        bySegment.set(entry.segment, {
          segment: entry.segment,
          segment_display: entry.segment_display || entry.segment,
          entry_type: entry.entry_type,
          file_count: 0,
          total_bytes: 0,
          dup_count: 0,
          presentHosts: [],
          dup_hash_count: 0,
          // Leaf file fields (last-wins from any host reporting them):
          filename: null,
          size_bytes: null,
          hash: null,
          mtime: null,
          last_seen_at: null,
          file_category: null,
          path_display: null,
          other_hosts: null,
        })
      }

      const m = bySegment.get(entry.segment)
      m.presentHosts.push(host)
      m.file_count += entry.file_count || 0
      m.total_bytes = (m.total_bytes || 0) + (entry.total_bytes || 0)
      m.dup_count += entry.dup_count || 0
      m.dup_hash_count += entry.dup_hash_count || 0

      // Use the first non-null values for display fields
      if (entry.segment_display) m.segment_display = entry.segment_display
      if (entry.filename) m.filename = entry.filename
      if (entry.size_bytes != null) m.size_bytes = entry.size_bytes
      if (entry.hash) m.hash = entry.hash
      if (entry.mtime != null) m.mtime = entry.mtime
      if (entry.last_seen_at) m.last_seen_at = entry.last_seen_at
      if (entry.file_category) m.file_category = entry.file_category
      if (entry.path_display) m.path_display = entry.path_display
      if (entry.other_hosts) m.other_hosts = entry.other_hosts
    }
  }

  return Array.from(bySegment.values())
}

// ─── Sorting ─────────────────────────────────────────────────────────────────

export function sortEntries(entries, sortBy, sortDir) {
  return [...entries].sort((a, b) => {
    // Dirs always first regardless of sort column
    if (a.entry_type !== b.entry_type) {
      return a.entry_type === 'dir' ? -1 : 1
    }
    let cmp = 0
    switch (sortBy) {
      case 'name':
        cmp = (a.segment_display || a.segment).localeCompare(b.segment_display || b.segment)
        break
      case 'size':
        cmp = (a.total_bytes || 0) - (b.total_bytes || 0)
        break
      case 'date':
        cmp = (a.mtime || 0) - (b.mtime || 0)
        break
      case 'hash':
        cmp = (a.hash || '').localeCompare(b.hash || '')
        break
      case 'seen':
        cmp = (a.last_seen_at || '').localeCompare(b.last_seen_at || '')
        break
      case 'type':
        cmp = (a.file_category || '').localeCompare(b.file_category || '')
        break
      default:
        cmp = (a.segment_display || a.segment).localeCompare(b.segment_display || b.segment)
    }
    return sortDir === 'asc' ? cmp : -cmp
  })
}

// ─── FileEntry → row conversion (for search / pinned results) ────────────────

/**
 * Convert a FileEntry (from /files API) into a FileTable row object.
 */
export function fileEntryToRow(fe) {
  const parts = (fe.path_display || '').split('/')
  const parentPath = parts.length > 1 ? parts.slice(0, -1).join('/') || '/' : '/'
  const entry = {
    segment: fe.filename,
    segment_display: fe.filename,
    entry_type: 'file',
    file_count: 1,
    total_bytes: fe.size_bytes,
    dup_count: 0,
    dup_hash_count: 0,
    presentHosts: [fe.host],
    filename: fe.filename,
    size_bytes: fe.size_bytes,
    hash: fe.hash,
    mtime: fe.mtime,
    last_seen_at: fe.last_seen_at,
    file_category: fe.file_category,
    path_display: fe.path_display,
    other_hosts: fe.other_hosts || null,
  }
  return { entry, parentPath, fullPath: fe.path_display, depth: 0 }
}

/**
 * Sort FileTable rows derived from FileEntry[] (no dirs; simpler than sortEntries).
 */
export function sortFileEntries(rows, sortBy, sortDir) {
  return [...rows].sort((a, b) => {
    const ae = a.entry, be = b.entry
    let cmp = 0
    switch (sortBy) {
      case 'size':  cmp = (ae.size_bytes || 0) - (be.size_bytes || 0); break
      case 'date':  cmp = (ae.mtime || 0) - (be.mtime || 0); break
      case 'hash':  cmp = (ae.hash || '').localeCompare(be.hash || ''); break
      case 'seen':  cmp = (ae.last_seen_at || '').localeCompare(be.last_seen_at || ''); break
      case 'type':  cmp = (ae.file_category || '').localeCompare(be.file_category || ''); break
      default:      cmp = (ae.filename || '').localeCompare(be.filename || ''); break
    }
    return sortDir === 'asc' ? cmp : -cmp
  })
}

// ─── File category guessing ──────────────────────────────────────────────────

const IMAGE_EXTS = new Set(['jpg','jpeg','png','gif','bmp','tiff','webp','heic','svg','ico','raw','cr2','nef','arw'])
const VIDEO_EXTS = new Set(['mp4','mkv','avi','mov','wmv','flv','m4v','ts','webm','mpeg','mpg'])
const AUDIO_EXTS = new Set(['mp3','flac','aac','ogg','wav','m4a','wma','opus'])
const DOC_EXTS   = new Set(['pdf','doc','docx','xls','xlsx','ppt','pptx','odt','ods','odp','txt','rtf','md'])
const CODE_EXTS  = new Set(['py','js','ts','jsx','tsx','java','c','cpp','h','rs','go','rb','php','sh','bash','css','html','json','yaml','yml','toml','sql'])
const ARCH_EXTS  = new Set(['zip','tar','gz','bz2','xz','rar','7z','tgz'])

export function guessCategory(filename) {
  const ext = (filename.split('.').pop() || '').toLowerCase()
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (VIDEO_EXTS.has(ext)) return 'video'
  if (AUDIO_EXTS.has(ext)) return 'audio'
  if (DOC_EXTS.has(ext))   return 'document'
  if (CODE_EXTS.has(ext))  return 'code'
  if (ARCH_EXTS.has(ext))  return 'archive'
  return 'other'
}
