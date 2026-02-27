const BASE = ''

async function get(path, params = {}) {
  const url = new URL(BASE + path, window.location.origin)
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') {
      url.searchParams.set(k, String(v))
    }
  })
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const api = {
  init: (path = '/') => get('/init', { path }),
  hosts: () => get('/hosts'),
  ls: (path, host, minSize = 0) => get('/files/ls', { path, host, depth: 1, min_size: minSize }),
  dupHash: (path, host, minSize = 0) => get('/files/ls/dup-hash', { path, host, min_size: minSize }),
  subtreeDups: (host, pathPrefix, minSize = 0, limit = 1000) =>
    get('/files/duplicates-in-subtree', { host, path_prefix: pathPrefix, min_size: minSize, limit }),
  dupDirAncestors: (host, pathPrefix, minSize = 0) =>
    get('/files/dup-ancestor-dirs', { host, path_prefix: pathPrefix, min_size: minSize }),
  files: (params) => get('/files', params),
  stats: (params = {}) => get('/stats/overview', params),
  directories: (q, limit = 10) => get('/directories', { q, limit }),
}
