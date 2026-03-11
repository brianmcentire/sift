# Code Review — March 2026 (v0.9.5)

Comprehensive review of the sift codebase, checked against steering documents
(`architecture-principles.md`, `duplicate-semantics.md`, `search-interaction-contract.md`)
and verified against the live production database (localhost:8765).

Updated from v0.9.3 review after frontend bug fixes, `minDupSize→minSize` rename,
DuckDB lock improvements, and doc updates.

---

## 1. Live Data Observations

### host_stats vs files table count discrepancy

The `/hosts` endpoint reports from `host_stats`, which uses
`WHERE skipped_reason IS NULL` in its `refresh_host_stats()` query.
The `files` table includes skipped rows (volatile, dataless, permission errors).

| Host | files table | host_stats | Delta |
|------|-------------|------------|-------|
| Unraid | 3,718,426 | 3,718,426 | 0 |
| bedroompi | 1,035 | 1,034 | +1 |
| rpi3b | 3,430 | 3,400 | +30 |
| Photoshop-PC | 1,114,431 | 1,114,311 | +120 |
| Brians-M2ProMBP | 818,678 | 817,400 | +1,278 |

The deltas exactly match null-hash file counts per host. This is by design —
`total_files` means "fully processed files", not "all rows". However:

**Gap:** The naming `total_files` is misleading. A user running `sift status`
sees "817,400 files" but the actual inventory contains 818,678 rows.
`total_indexed` or `total_hashed_or_skipped` would be more honest, or the
UI/CLI could show both counts.

### Stale aggregates after scan — RESOLVED

Maintenance worker is now enabled by default (`SIFT_MAINTENANCE_ENABLED=1`).
After scan completion, stale global aggregates (`hash_stats`, `directory_index`)
are picked up by the background worker after the 120s idle cooldown.
`sift status` shows `dup stats stale/building` in the summary line when
aggregates are not fresh, and `sift status -v` shows per-aggregate detail.
Server logs maintenance job start/completion with elapsed time.

---

## 2. Architecture Principles Compliance

### Verified correct

- **Hash locally, post to server** — scan.py computes SHA-256 on-host, POSTs metadata.
- **Normalize paths at ingest** — `normalize_path_for_storage()` called before every upsert.
- **Store absolute paths** — `os.path.realpath()` in `normalize_query_path()`.
- **Idempotent ingestion** — `INSERT ... ON CONFLICT DO UPDATE` in `/files` POST.
- **Scoped tombstoning** — `last_seen_at` + scan root context; `sift trim --deleted` uses covering roots.
- **No executemany in production** — `db.executemany()` is defined but never called by server endpoints. Only used in test conftest `insert_files()` helper (acceptable for test setup).
- **Bulk UPDATE patterns** — `/files/seen` uses single `UPDATE ... WHERE (host, drive, path) IN (VALUES ...)`. `/files` POST uses multi-row `INSERT`. Both correct.
- **Single RLock** — all DB operations under `_lock`. Correct for safety, though reader-writer separation would improve concurrency.

### Minor deviations

- **`executemany()` function exported from db.py** — dead code in production but available for misuse. Consider removing it or adding a deprecation warning. The test conftest is the only caller; test helpers could use `execute()` with multi-row VALUES instead.

---

## 3. Server Code (server/main.py, server/db.py)

### Query cache invalidation — intentional design

`POST /files` (ingest) invalidates all caches including `_tree_children_cache`, `_tree_dup_metrics_cache`, `_directories_cache`, etc. `POST /files/seen` (seen-path updates) does NOT invalidate any cache. This is intentional — seen updates only touch `last_seen_at` and don't change tree structure or dup counts. Documented here as a design decision.

### Aggregate freshness gating inconsistency

Different endpoints handle stale aggregates differently:
- `/files/duplicates-by-subtree-hashes` — returns HTTP 202 if any selected host is not fresh. Correct.
- `/files/page` with `has_duplicates=true` — returns 202. Correct.
- `/files/duplicates-in-subtree` — falls back to live query if aggregates missing (expensive on large hosts). Could be very slow on 800k+ file hosts. **Still open:** lacks explicit freshness check (uses existence check only).
- `/tree/dup-metrics` with multi-host `hosts` param — returns `data_freshness: "stale"` with empty metrics. Correct but silent.
- `/stats/overview` — NOW returns `data_freshness` field, partially closing the staleness gap.

**Gap:** No fully consistent contract for "what does the client see when aggregates are stale?" The frontend handles this ad-hoc per endpoint.

### Magic numbers — MOSTLY RESOLVED

Most operational thresholds are now configurable via env vars:
- `SIFT_QUERY_CACHE_TTL` (default 300)
- `SIFT_QUERY_CACHE_MAX` (default 2000)
- `SIFT_MAINTENANCE_COOLDOWN_SEC` (default 10)
- `SIFT_MAINTENANCE_MIN_IDLE_SEC` (default 120)
- `SIFT_DUP_METRICS_LIVE_MAX_FILES` (default 200000)

**Still hardcoded:**
- Size bucket boundaries: `_SIZE_100_KB`, `_SIZE_1_MB`, etc.
- Cross-host dup logic: `>= 3 copies AND >= 2 hosts` (hardcoded in report SQL)

These are reasonable as hardcoded values — low change frequency, high semantic coupling.

### DuckDB lock error handling — NEW

`DBTimeoutError` class in `db.py` with `timeout_type` field (`lock_wait` or `query_timeout`).
Timeout-protected lock acquisition prevents indefinite hangs. Exception handler in
`main.py` returns 503 (lock wait) or 504 (query timeout). Pre-flight DB lock check
in `sift/commands/server.py` catches stale lock files before uvicorn starts.

### Thread safety — background startup refresh

The startup refresh thread (`_startup_refresh_aggregates()`) runs `refresh_host_stats`, `refresh_host_hash_stats`, `refresh_hash_stats`, and `refresh_directory_index` in sequence. Each acquires the lock. If the first scan completes while startup refresh is still running, the scan's post-completion aggregate enqueue could deadlock with the refresh thread on the RLock. However, since `RLock` is reentrant within a single thread, and these are different threads, they'll just serialize. Performance concern, not a bug.

---

## 4. CLI Code

### scan.py — fresh_mtime_threshold_seconds not in config defaults

Line ~459 of scan.py reads `cfg.get("fresh_mtime_threshold_seconds", 60)` but this key is not documented in `config.py`'s `_DEFAULT` dict. The hardcoded fallback of 60 works, but users can't discover or configure it.

### exclusions.py — macOS iCloud path segment matching could false-positive

The macOS iCloud directory exclusion uses substring matching on path segments:
```python
if seg in path_lower:  # where seg = "/library/mail", etc.
```

This could false-positive on paths like `/mnt/mail_backup/` (contains `/mail`) on Darwin. The current excluded segments are specific enough (`/library/mail`, `/library/messages`, `/library/mobile documents`) that this is unlikely in practice, but the matching technique is fragile.

### upgrade.py — fragile editable-install detection

`_is_editable()` does string matching on `direct_url.json`:
```python
return '"editable": true' in text
```

This will break if pip changes the JSON field ordering or escaping. Should use `json.loads()`.

---

## 5. Frontend Code (App.jsx, api.js)

### Reset doesn't clear overlay result arrays — RESOLVED

`filenameResults`, `hashResults`, and `highlightedPaths` are now cleared in the reset
handler (lines 899-901). `listItems`, `listCursor`, `listHasMore`, and `listLoading`
are also cleared (lines 902-905).

### categoryFilter change doesn't invalidate dup-metrics cache — RESOLVED

`categoryFilter` is now in the invalidation `useEffect` dep array (line 338), and
`categoriesCsv` is included in `metricKey` (line 433), so cached metrics are correctly
invalidated and re-keyed when categories change.

### Overlay sorting — deferred (not a bug)

Subtree duplicate overlays use fixed hash→path→filename sort order. The user's sort
column selection is ignored. `search-interaction-contract.md` marks this as `[TBD]`.
Documented, not blocking.

### Category filter trap — RESOLVED

`availableCategories` now correctly derives from unfiltered source data, preventing the
empty-state trap where users couldn't deselect a category with no results.

### Host selection dup-metrics invalidation — RESOLVED

`selectedHosts` now has its own `useEffect` (line 334-338) that clears
`dupMetricSegmentsRef` and `dupMetricsInFlightRef`. Host switches properly
invalidate cached dup metrics. ✓

### Verified correct behaviors

- **Hash search bypasses size/category filters** — `isDupQuery` flag gates filter application ✓
- **Subtree overlay hides list icon on file rows** ✓
- **Overlay highlight precedence** (blue > amber > orange) ✓
- **minSize invalidates dup-metrics cache** (line 324-332) ✓
- **`isDup` semantics** — `dup_count > 0 || otherHostList.length > 0` ✓
- **`other_hosts`** drives cross-host highlight (not `presentHosts.length > 1`) ✓

### Dead API methods in api.js

- `api.init()` — defined, never called from frontend
- `api.ls()` — defined, never called (tree uses `treeChildren` + `treeDupMetrics`)
- `api.subtreeDups()` — defined, only `api.duplicatesBySubtreeHashes()` is used

Note: `api.duplicatesInSubtree()` was removed. `api.dupHash()` IS used (line 1197).

These are harmless but add confusion. Consider cleaning up in a future pass.

### localStorage filter persistence — NOT IMPLEMENTED

MEMORY.md documents `sift-filters` localStorage persistence, but no `localStorage`
code exists in App.jsx. This was likely lost in a commit rollback and needs
reimplementation.

---

## 6. Test Coverage

### Unit test inventory (current)

| File | Tests | Coverage area |
|------|-------|---------------|
| `test_resolve_host.py` | 9 | resolve_host() function |
| `test_normalize.py` | 8 | normalize_query_path() edge cases |
| `test_classify.py` | 10 | Edge cases: empty, unicode, spaces, dotfiles, camera RAW |
| `test_hash_utils.py` | 8 | Error scenarios: deleted file, directory, large content, permissions |
| `test_commands_status.py` | 1 | localhost resolution in status command |
| `test_config.py` | — | Config loading |
| `test_config_validation.py` | — | Config validation |
| `test_commands_init.py` | — | Init command |
| `test_commands_ls_du_tree_api.py` | — | ls/du/tree API commands |
| `test_commands_find.py` | — | find command |
| `test_commands_report.py` | — | report command |
| `test_commands_trim.py` | — | trim command |
| `test_exclusions.py` | — | File/dir exclusion logic |
| `test_scan.py` | — | Scan agent |
| `test_scan_null_hash_retry.py` | — | Null hash retry logic |
| `test_db_timeouts.py` | — | DuckDB timeout handling (NEW) |

### Significant gaps remaining

| Area | What's missing | Risk |
|------|---------------|------|
| Scan error recovery | No tests for permission denied, disk full, file-disappears-mid-read | Scan could silently lose data or crash |
| Server error responses | No tests for malformed payloads, oversized requests, timeout responses | Unknown behavior on bad input |
| Trim safety | No tests verifying wrong-host or wrong-path protection | Destructive command with limited guardrails |
| Concurrent access | No tests for simultaneous scans, scan+trim, multi-client | Race conditions possible |
| Config parsing errors | No tests for malformed TOML, permission denied on config file | Cryptic errors for users |
| Report timeout | No tests for API timeout during report generation | Hangs indefinitely |
| Large dataset behavior | No tests with 10k+ files | Performance cliffs unknown |
| Frontend | No unit/component tests at all | Regressions caught only manually |

---

## 7. Documentation Gaps

### search-interaction-contract.md has open TBDs — reduced to 2

Two items marked `[TBD]` that affect current behavior:
1. Directory input behavior during overlay states (currently composable but undocumented)
2. Overlay group sorting contract (currently fixed-order, ignores user sort)

~~3. Regression checklist for search transitions~~ — **DONE** (`frontend-regression-checklist.md` exists)

### duplicate-semantics.md freshness section — DONE

The document now has a Freshness section covering badge/count staleness behavior.

### pyproject.toml version — DONE

Version is 0.9.5.

### localStorage filter persistence — MISSING

MEMORY.md documents `sift-filters` localStorage save/restore, but the implementation
was lost in a commit rollback. Needs reimplementation.

---

## 8. Summary

### What's working well

- Architecture principles are faithfully implemented across the codebase
- Bulk DB patterns are correct everywhere in production code
- Hard link detection and exclusion is thorough and well-tested
- Network mount exclusion is comprehensive with good platform coverage
- Scan error recovery (retry, backoff, Ctrl-C handling) is robust
- Duplicate semantics in the frontend match the spec accurately
- The steering documents are genuinely useful and code follows them
- Server operational thresholds now configurable via env vars
- DuckDB lock timeouts prevent indefinite hangs (DBTimeoutError)
- `/stats/overview` returns `data_freshness` field
- Category filter trap resolved (availableCategories from unfiltered source)
- Host selection properly invalidates dup-metrics cache
- Reset handler fully clears all filter, overlay, and list-view state
- categoryFilter correctly invalidates dup-metrics cache (dep array + metricKey)
- Windows drive tree path collision fixed (drive children namespaced as `__drive__:C/path`)

### Priority fixes

All previously listed HIGH/CRITICAL frontend bugs have been resolved:

1. ~~**CRITICAL: `setMinDupSize(0)` → `setMinSize(0)` in reset handler**~~ — RESOLVED
2. ~~**HIGH: Reset must clear `filenameResults`, `hashResults`, `highlightedPaths`**~~ — RESOLVED
3. ~~**HIGH: Reset must clear `listItems`, `listCursor`, `listHasMore`, `listLoading`**~~ — RESOLVED
4. ~~**HIGH: Add `categoryFilter` to dup-metrics cache invalidation**~~ — RESOLVED

Remaining:

5. **Reimplement localStorage filter persistence** — `sift-filters` save/restore lost in rollback

### Considerations for future

- `fresh_mtime_threshold_seconds` → add to `config.py` `_DEFAULT` dict
- `upgrade.py` — use `json.loads()` for editable detection
- Overlay sorting contract (marked TBD in steering doc)
- Clean up unused API methods in `api.js` (`init`, `ls`, `subtreeDups`)
- `/files/duplicates-in-subtree` explicit freshness gating

### Things that are fine as-is

- `executemany()` existing in db.py (unused in production, only test conftest)
- Hardcoded size buckets and cross-host dup thresholds (low change frequency)
- Hardcoded extension lists in classify.py (comprehensive, easy to extend)
- Single RLock instead of reader-writer lock (correct for current scale)
- `host_stats` excluding skipped files (intentional, just needs clearer naming)
- `POST /files/seen` skipping cache invalidation (intentional — only touches `last_seen_at`)
