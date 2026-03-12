# Drive-Aware Directory Search — Implementation Plan

## Problem

Directory search ("folder to open...") in Tree View fails for Windows multi-drive hosts.
The search works for POSIX hosts (e.g. rpi3b) but not for Windows hosts with multiple
drives (e.g. photoshop-pc with C: and D:).

### Root causes

1. **`directory_index` is not host/drive-aware.** Schema is `(dir_path TEXT PRIMARY KEY)`.
   `normalize.py` strips the drive letter, so `C:/Users/Brian` and `D:/Users` both store
   as `/users/brian` and `/users` with no host or drive attribution. The `/directories`
   endpoint returns only `dir_path` and `dir_display`.

2. **Frontend path namespace mismatch.** Tree rows for multi-drive Windows hosts use
   synthetic UI paths (`__drive__:C/users/brian`). The search effect at `App.jsx:855`
   puts raw `dir_path` values (`/users/brian`) into `matchedDirPaths` and `toExpand`.
   The `has()` checks at lines 1830 and FileRow.jsx:179 compare against `row.fullPath`
   which is in UI-path form — so they never match.

3. **Ancestor prefetch uses wrong drive.** `fetchPath` at line 874 relies on
   `hostDrive(h.host)` which returns `activeDrive` for multi-drive hosts. If no drive
   node has been expanded yet, `activeDrive` is empty, so the fetch targets the wrong
   cache key.

4. **List View `path_contains` breaks on drive-qualified input.** If a user types
   `D:\videos`, the raw string is sent as `path_contains` to `/files/page` (line 631).
   `f.path` is drive-stripped, so the match always fails silently.

5. **Overlay client-side filter breaks on drive-qualified input.** The filter at
   line 1571 matches `dirQuery` against `path_display` (which uses forward slashes).
   A backslash-style query like `D:\videos` won't match `D:/Users/Videos`.

### Affected views

| View | Symptom |
|------|---------|
| Tree View — dir search | No expansion, no highlight for Windows multi-drive paths |
| Tree View — prefetch | Wrong or missing cache entries for search ancestors |
| List View — path_contains | Drive-qualified queries silently return zero results |
| Overlay — client filter | Backslash drive prefix won't match forward-slash `path_display` |

## Design decisions

- **UI-path form early (Option A).** Convert `/directories` results to UI-path form
  (`__drive__:C/users/brian` or `/home/pi`) immediately after the API response. All
  downstream consumers (`matchedDirPaths`, `toExpand`, `fetchPath` calls) use UI paths.
  This is cheaper (one transform pass) and avoids dual data structures or reverse lookups.

- **All search-path comparisons use normalized lowercase UI-path form.** This matches
  the existing `fullPath` behavior in the tree (built from lowercased `dir_path` values).
  Both `matchedDirPaths` entries and `toExpand` ancestors are lowercase, so `has()` checks
  against `row.fullPath` are always case-consistent. No `.toLowerCase()` at comparison
  sites — correctness comes from consistent normalization at the point of construction.

- **Drive-qualified query parsing in frontend.** Detect `D:\...` or `D:/...` prefix
  via regex `/^([a-zA-Z]):[/\\]/`. Strip prefix from the query string sent to the server;
  pass `drive` as a separate filter param. If no drive prefix, all drives are searched.
  The raw input remains in the `dirQuery` state (visible in the search box).

- **`/directories` becomes host/drive-aware.** Returns `host`, `drive`, `dir_path`,
  `dir_display`. Accepts `hosts` (CSV, required) and optional `drive` filter params.
  `hosts` is required to reduce complexity — there is no use case for unfiltered
  cross-host search, and requiring it avoids a code path that returns irrelevant results.

- **`/files/page` gets optional `drive` filter.** Honors drive constraint in List View
  when the user explicitly includes a drive letter.

- **Single-drive Windows hosts are unaffected.** They use the `noDriveHosts` branch
  (App.jsx:1376) with plain POSIX-style fullPath values. No `__drive__:` namespace.

- **Shared drive-letter collisions.** If two selected multi-drive hosts both have `D:`
  and both contain the same normalized path, the tree model already merges them under
  one synthetic `__drive__:D/...` branch. The `/directories` endpoint may return
  separate rows for each `(host, drive, dir_path)` tuple, but the frontend UI-path
  transform deduplicates them into the same UI path (e.g. both map to
  `__drive__:D/users/videos`). `matchedDirPaths` is a `Set`, so duplicates collapse
  naturally. This is consistent with existing tree merge semantics.

## Performance considerations

- `directory_index` grows from ~N rows to ~N×hosts×drives rows. For a typical 2-host
  setup with 2 drives on one host, that's roughly 3× the current row count. Still small
  (directory count, not file count). The `LIKE` query gains a `host IN (...)` filter
  that actually reduces scan scope vs. today's unfiltered query.
- Cache key for `/directories` changes from `(q, limit)` to `(q, hosts_key, drive, limit)`.
  More cache partitions but each partition is smaller. Net effect: neutral.
- Frontend: one pass over `/directories` results to transform to UI paths. O(results).
  Ancestor expansion is O(results × depth). Same as today, just correct.
- `fetchPath` calls for ancestors use `opts.drive` override — no change to fetch
  mechanics or API call count. Drive-specific calls are already the norm for expanded
  drive nodes.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| `directory_index` migration on existing DBs | `DROP TABLE + DROP INDEX + RECREATE` in `_run_migrations()`. Table is fully rebuilt by `refresh_directory_index()` on next maintenance run. Brief empty-results window after restart is acceptable. |
| Same normalized path on C: and D: now returns separate results | Correct behavior — they are different directories. Frontend deduplicates into shared UI path when hosts merge under same drive node. |
| Mixed host selections (Windows + Linux) | Each result carries `host`+`drive`; frontend maps Linux results to plain paths and Windows to `__drive__:` paths in the same `matchedDirPaths` set. |
| Cache invalidation for `/directories` now includes `hosts` | `invalidate_caches()` already clears the entire `_directories_cache` dict. No change needed. |
| Ancestor-highlight logic in `/directories` (lines 3819-3831) builds ancestors from `dir_path` | Ancestors emitted per `(host, drive)` tuple. Proportional growth is negligible at directory-count scale. |
| Existing integration tests assert `dir_path` / `dir_display` fields | Tests updated to also assert `host` and `drive` fields. |
| Drive-qualified query in overlay client filter | Same `parseDirQuery` function strips prefix; uses path portion for `includes()` match. |

## Key invariant: ancestor construction for `__drive__:` paths

Generic `split('/')` ancestor logic **cannot** be reused unchanged for `__drive__:`-prefixed
UI paths. A dedicated helper is required that handles both path forms:

- **Plain POSIX path** `/home/pi/videos`:
  ancestors = `["/home", "/home/pi"]` (standard split-and-rejoin)

- **Drive-namespaced path** `__drive__:D/users/videos`:
  ancestors = `["__drive__:D", "__drive__:D/users"]`
  - `__drive__:D` is the synthetic drive node — include in `toExpand` but do NOT
    call `fetchPath` for it (it has no server-side path to fetch).
  - `__drive__:D/users` is a real path — `fetchPath` with `path=/users`, `drive=D`.

The helper must:
1. Detect `__drive__:` prefix and split accordingly.
2. Return ancestors in UI-path form.
3. Distinguish fetchable ancestors from synthetic drive nodes.
4. Keep all paths in normalized lowercase form.

This helper (`buildUiAncestors` or similar) is exported from `utils.js` and unit-tested
(see Phase 5).

## Phases

### Phase 1: Server — make `directory_index` and `/directories` host/drive-aware
- [x] 1a. Add migration in `db.py:_run_migrations()`: drop `idx_dir_index_path` index, drop `directory_index` table, recreate with schema `(host TEXT NOT NULL, drive TEXT NOT NULL DEFAULT '', dir_path TEXT NOT NULL, dir_display TEXT, updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (host, drive, dir_path))`. Recreate index as `idx_dir_index_host_path ON directory_index(host, dir_path)`.
- [x] 1b. Update `refresh_directory_index()` in `db.py` to `GROUP BY host, drive, regexp_replace(path, '/[^/]+$', '')` pulling `host` and `drive` from the `files` table.
- [x] 1c. Update `/directories` endpoint in `server/main.py` to:
  - Accept `hosts: str = Query(...)` (CSV, required) and `drive: str = Query("")` (optional) params.
  - Add `AND host IN (...)` filter using the parsed host list.
  - Add `AND drive = upper(?)` filter when `drive` is non-empty.
  - Return `host`, `drive`, `dir_path`, `dir_display` in each result object.
  - Update cache key to `(q.lower(), hosts_key, drive.upper(), limit)`.
  - Update the fallback query with the same host/drive filters.
  - Update ancestor-highlight logic to emit ancestors per `(host, drive)` tuple.
- [x] 1d. Add `drive: str = Query("")` param to `/files/page` in `server/main.py`. When non-empty, add `AND f.drive = upper(?)` to the WHERE clause.

### Phase 2: Frontend — drive-qualified query parsing and ancestor helper
- [x] 2a. Add `parseDirQuery(raw)` to `utils.js`. Returns `{ drive: string, pathQuery: string }`. Regex `/^([a-zA-Z]):[/\\]/` detects drive prefix. If matched: `drive` = uppercase letter, `pathQuery` = remainder (ensure leading `/`). If not matched: `drive` = `''`, `pathQuery` = raw input.
- [x] 2b. Add `dirResultToUiPath(host, drive, dirPath, hostMap)` to `utils.js`. Looks up host in `hostMap` to determine if multi-drive. Multi-drive + non-empty drive → `__drive__:${drive}${dirPath}`. Otherwise → `dirPath`.
- [x] 2c. Add `buildUiAncestors(uiPath)` to `utils.js`. Returns `{ ancestors: string[], driveNode: string|null }`. For `__drive__:X/a/b` → ancestors `["__drive__:X", "__drive__:X/a"]`, driveNode `"__drive__:X"`. For `/a/b/c` → ancestors `["/a", "/a/b"]`, driveNode `null`. The caller uses `driveNode` to skip `fetchPath` for synthetic nodes.
- [x] 2d. Add `parsedDirQuery` memoization in `App.jsx` — `useMemo` over `debouncedDirQuery` calling `parseDirQuery`. Also `hostMap` memo for `dirResultToUiPath`.

### Phase 3: Frontend — fix Tree View directory search effect
- [x] 3a. Update `api.directories()` in `api.js` to accept and pass `hosts` (required) and `drive` (optional) params.
- [x] 3b. Update the directory search `useEffect` to use `parsedDirQuery`, `dirResultToUiPath`, `buildUiAncestors`, and drive-aware `fetchPath` calls. Also fixed `visiblePaths` building in tree row filter to use `buildUiAncestors` instead of naive `split('/')`.

### Phase 4: Frontend — fix List View and overlay
- [x] 4a. Update List View fetch to use `parsedDirQuery.pathQuery` for `path_contains` and pass `parsedDirQuery.drive` as `drive` param to `/files/page`.
- [x] 4b. `drive` param passed inline via the existing `params` object (no `api.filesPage()` signature change needed — it already passes params through).
- [x] 4c. Update overlay client-side filter to use `parsedDirQuery.pathQuery` instead of raw `dirQuery` for the `path_display` substring match.

### Phase 5: Tests
- [x] 5a. Add unit tests in `frontend/src/utils.test.js` for `parseDirQuery` (9 tests), `dirResultToUiPath` (6 tests), `buildUiAncestors` (6 tests). All 30 tests pass.
- [x] 5b. Update integration tests in `tests/integration/test_live.py` (`TestLiveDirectories`) to pass `hosts` param and assert `host` and `drive` fields in `/directories` results.
- [x] 5c. Update `tests/server/test_query_cache.py` `/directories` cache tests for new required `hosts` param and response shape (4 tests pass).
- [x] 5d. Verify manually: search for a folder name that exists on both C: and D: — both drive nodes should expand with correct highlights. Search with `D:\` prefix — only D: results appear. Mixed host selection (Windows + Linux) expands both host paths correctly.

### Phase 6: Cleanup
- [x] 6a. Bump version in `pyproject.toml` (0.9.7 → 0.9.8).
- [ ] 6b. Update `search-interaction-contract.md` § Input Semantics to document drive-qualified directory input behavior.
