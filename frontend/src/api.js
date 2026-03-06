import { logPerf } from './utils.js'

const BASE = ''

async function get(path, params = {}, options = {}) {
  const started = performance.now()
  const url = new URL(BASE + path, window.location.origin)
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') {
      if (Array.isArray(v)) {
        v.forEach(item => url.searchParams.append(k, String(item)))
      } else {
        url.searchParams.set(k, String(v))
      }
    }
  })
  const res = await fetch(url.toString(), { signal: options.signal })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  const data = await res.json()
  const elapsedMs = (performance.now() - started).toFixed(1)
  const rows = Array.isArray(data)
    ? data.length
    : Array.isArray(data?.files)
      ? data.files.length
      : '-'
  logPerf('api.get', {
    path,
    ms: elapsedMs,
    rows,
    params: Object.keys(params).length,
  })
  return data
}

export const api = {
  init: (path = '/', options = {}) => get('/init', { path }, options),
  hosts: (options = {}) => get('/hosts', {}, options),
  ls: (path, host, drive = '', minSize = 0, options = {}) => get('/files/ls', { path, host, drive, depth: 1, min_size: minSize }, options),
  treeChildren: (path, host, query = {}, drive = '', options = {}) => get('/tree/children', {
    path,
    host,
    drive,
    depth: 1,
    limit: query.limit ?? 200,
    cursor: query.cursor,
  }, options),
  treeDupMetrics: (path, host, minSize = 0, segments = [], drive = '', options = {}) => get('/tree/dup-metrics', {
    path,
    host,
    drive,
    depth: 1,
    min_size: minSize,
    segments: Array.isArray(segments) && segments.length > 0 ? segments : undefined,
  }, options),
  dupHash: (path, host, minSize = 0, drive = '', options = {}) => get('/files/ls/dup-hash', { path, host, drive, min_size: minSize }, options),
  subtreeDups: (host, pathPrefix, minSize = 0, limit = 1000, drive = '') =>
    get('/files/duplicates-in-subtree', { host, drive, path_prefix: pathPrefix, min_size: minSize, limit }),
  dupDirAncestors: (host, pathPrefix, minSize = 0, maxPaths = 500, drive = '') =>
    get('/files/dup-ancestor-dirs', { host, drive, path_prefix: pathPrefix, min_size: minSize, max_paths: maxPaths }),
  filesPage: (params, options = {}) => get('/files/page', params, options),
  files: (params, options = {}) => get('/files', params, options),
  stats: (params = {}, options = {}) => get('/stats/overview', params, options),
  directories: (q, limit = 10, options = {}) => get('/directories', { q, limit }, options),
  clientHost: (options = {}) => get('/client-host', {}, options),
}
