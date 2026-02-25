# Deferred Features

Features intentionally left for future development.

---

## `sift dups`
Duplicate analysis command: top wasted space, breakdown by category, host intersection/difference.

## `sift purge`
Safe interactive deletion of confirmed duplicates.

## `sift shell`
REPL with `cd`/`ls`/`find` against the inventory. Includes `rm` for removing inventory entries (not files).

---

## Host-Aware Dup Semantics

**Context:** Today "is this a duplicate?" has one meaning regardless of which hosts are selected.
The desired behavior is three distinct semantic modes driven by the host chip selection:

### Three modes

| Selection | `isDup` definition |
|---|---|
| **All hosts** | current behavior — dup if `dup_count > 0` OR same hash exists on any other host |
| **Single host** | within-host only — dup if `dup_count > 0` on that host; cross-host matches ignored |
| **2+ but not all hosts** | union — dup if `dup_count > 0` on any selected host OR same hash exists on any other selected host |

In union mode the user chose **union** (not intersection) — "what's redundant within this group of hosts?"

### What needs to change

#### Frontend (`App.jsx`, `utils.js`)

1. Derive `dupMode: 'all' | 'single' | 'multi'` from `selectedHosts.size` vs `hosts.length`.
2. Pass `dupMode` + `selectedHosts` into `mergeEntries` / wherever `isDup` is computed today.
3. Rewrite `isDup` logic:
   - `all`: `dup_count > 0 || Boolean(other_hosts)` ← unchanged
   - `single`: `dup_count > 0` ← ignore `other_hosts`
   - `multi`: `dup_count > 0 || other_hosts.split(',').some(h => selectedHosts.has(h))`
     (`other_hosts` already contains all other-host names for the same hash)
4. `onlyDups` toggle and `isDup`-derived row colouring (amber) both use the mode-appropriate definition.
5. **StatsBar `isFiltered` label**: host selection in `single` or `multi` mode should arguably
   display `(filtered)` since numbers differ from global totals.  Currently only `minDupSize > 0`
   or `categoryFilter.size > 0` triggers the label — extend the condition.

#### Server `/files/ls`

`dup_count` on directory entries is currently same-host only (computed from the `dupes` CTE which
filters `WHERE host = ?`).  For union mode, directory `dup_count` should also count files in that
directory whose hash appears on any other selected host.

- Add optional `selected_hosts: str` query param (comma-separated) to `/files/ls`.
- When provided and `len > 1`, widen the `dupes` CTE:
  ```sql
  -- current (single-host)
  dupes AS (
      SELECT hash FROM files
      WHERE hash IS NOT NULL AND host = ? AND size_bytes >= ?
      ...
      GROUP BY hash HAVING COUNT(*) > 1
  )
  -- multi-host union
  dupes AS (
      SELECT hash FROM files
      WHERE hash IS NOT NULL AND host IN (?, ?) AND size_bytes >= ?
      GROUP BY hash HAVING COUNT(*) > 1
  )
  ```
  The outer `scoped` CTE still filters `WHERE f.host = ?` (we're building one host's tree view),
  so `dup_count` becomes "files in this dir/file on this host whose hash appears 2+ times across
  all selected hosts."
- When `len == 1` (single-host), keep the current same-host-only CTE.
- Frontend `fetchPath` must pass `selected_hosts` param when in multi mode.
- **Cache key** must include the selected-hosts set, or the cache must be busted when `dupMode`
  changes (similar to `lsFetchKey` pattern used for `minDupSize`).

#### Server `/stats/overview`

Already handles all three modes correctly via the `hosts` comma-separated param added in the
previous session:
- No host param → all-hosts totals (mode: all)
- Single host → same-host dups only (mode: single) — the `HAVING COUNT(*) > 1` naturally scopes
  to only that host's files
- Multiple hosts → union pool (mode: multi) — counts any hash appearing 2+ times across the
  combined pool of selected hosts

No further server changes needed for stats.

### Open questions / decisions for implementation

- **`dup_hash_count` for dirs in multi mode**: currently used for `extraCopies =
  dup_count - dup_hash_count`.  May need a matching `multi_dup_hash_count` column or a
  revised formula.
- **Cache invalidation**: adding `selected_hosts` to the ls cache key could fragment the cache
  heavily.  An alternative is to always fetch with all-hosts semantics and apply the filter
  client-side, but that requires the server to return both same-host AND cross-host dup counts
  in every ls response — a larger schema change.
- **Hard-link interaction**: in multi-host union mode, hard links on a single host should still
  be excluded from dup counts (same physical file).  The existing hard-link CTE already scopes
  to the current host, so this is likely fine as-is.

---

## Scan Cache Performance / Data Store Optimization

**Context:** At scan startup, `GET /files/cache` fetches every previously-indexed file (path +
mtime + size) for the scanned host/root as a single response. On large roots this can be 10MB+
of JSON and cause a 30–60s apparent freeze before scanning begins.

**Partial mitigations already in place:**
- Compact array-of-arrays response format (eliminates per-row JSON key overhead ~40% smaller)
- UX: "Fetching file cache... N entries." message so the user knows what's happening

**Remaining bottlenecks to investigate:**
- DuckDB `LIKE` on `path` column has no B-tree index — full table scan on every cache fetch
- The global `threading.RLock()` blocks all other db operations during the fetch
- Entire result set is buffered in Python before being serialized — streaming would help on huge roots

**Potential approaches:**
- Add a DuckDB index on `(host, path)` — DuckDB supports `CREATE INDEX` as of v0.10; measure
  whether it actually helps on columnar storage (may not for LIKE prefix scans)
- Stream the cache response with FastAPI `StreamingResponse` + NDJSON so parsing can begin
  before the full response arrives
- Store the cache locally (e.g. SQLite in `~/.sift-cache.db`) so startup is a local read
  instead of a network round-trip — invalidate on server-side hash changes
- Evaluate alternative embedded stores (e.g. Lance, SQLite + FTS5) if DuckDB proves
  fundamentally slow for the point-query / LIKE patterns sift uses at scale

---

## Server: `is_scanning` field on `/hosts`

**Context:** `last_scan_at` in `/hosts` is derived from `MAX(started_at)` on `scan_runs` filtered to
`status = 'complete'` only. A host mid-scan has no completed runs, so `last_scan_at` is NULL.

**Deferred fix:** Add `is_scanning: bool` to the `HostEntry` response model — a simple
`EXISTS (SELECT 1 FROM scan_runs WHERE host = ? AND status = 'running')` per host. The web UI
could then show a scanning indicator, and the CLI could use it directly rather than
cross-referencing scan runs.

**Current workaround:** CLI cross-references the `/scan-runs` response to detect running scans
and displays "scanning..." in the last scan column.
