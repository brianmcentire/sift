# Code Review — March 2026

Comprehensive review of the sift codebase, checked against steering documents
(`architecture-principles.md`, `duplicate-semantics.md`, `search-interaction-contract.md`)
and verified against the live production database (localhost:8765).

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

### Stale aggregates after scan

After the most recent MBP scan, `hash_stats` and `directory_index` are
marked `stale` in `aggregate_meta`. The maintenance worker should have
picked these up but appears to not have run. If `SIFT_MAINTENANCE_ENABLED`
is not set (default: disabled), aggregates only refresh on scan completion
via `PATCH /scan-runs`. If the maintenance worker is disabled and the
post-scan enqueue fails or the job dequeue never fires, aggregates stay
stale indefinitely.

**Gap:** No alerting or CLI visibility into stale aggregates. `sift status`
does not show aggregate freshness. Consider adding a `--health` flag or
including freshness in `sift status --stats`.

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

### Query cache invalidation inconsistency

`POST /files` (ingest) invalidates all caches including `_tree_children_cache`, `_tree_dup_metrics_cache`, `_directories_cache`, etc. But `POST /files/seen` (seen-path updates) does NOT invalidate any cache, even though it updates `last_seen_at` which affects "last seen" column visibility. This is likely intentional (seen updates don't change tree structure or dup counts) but should be documented as a design decision.

### Aggregate freshness gating inconsistency

Different endpoints handle stale aggregates differently:
- `/files/duplicates-by-subtree-hashes` — returns HTTP 202 if any selected host is not fresh. Correct.
- `/files/page` with `has_duplicates=true` — returns 202. Correct.
- `/files/duplicates-in-subtree` — falls back to live query if aggregates missing (expensive on large hosts). Could be very slow on 800k+ file hosts.
- `/tree/dup-metrics` with multi-host `hosts` param — returns `data_freshness: "stale"` with empty metrics. Correct but silent.
- `/stats/overview` — uses aggregates when available, falls back to live. No 202, no staleness indicator in response.

**Gap:** No consistent contract for "what does the client see when aggregates are stale?" The frontend handles this ad-hoc per endpoint. The duplicate-semantics.md doesn't specify fallback behavior.

### Magic numbers scattered in main.py

- `_DUP_METRICS_LIVE_MAX_FILES = 200_000` — threshold for live fallback
- `_MAINTENANCE_COOLDOWN_SEC = 10`, `_MAINTENANCE_MIN_IDLE_SEC = 120`
- `_QUERY_CACHE_TTL = 300`, `_QUERY_CACHE_MAX = 2000`
- Size bucket boundaries: `_SIZE_100_KB`, `_SIZE_1_MB`, etc.
- Cross-host dup logic: `>= 3 copies AND >= 2 hosts` (hardcoded in report SQL)

These are reasonable defaults but not configurable via env vars or config. If any need tuning in production, it requires a code change + redeploy.

### Thread safety — background startup refresh

The startup refresh thread (`_startup_refresh_aggregates()`) runs `refresh_host_stats`, `refresh_host_hash_stats`, `refresh_hash_stats`, and `refresh_directory_index` in sequence. Each acquires the lock. If the first scan completes while startup refresh is still running, the scan's post-completion aggregate enqueue could deadlock with the refresh thread on the RLock. However, since `RLock` is reentrant within a single thread, and these are different threads, they'll just serialize. Performance concern, not a bug.

---

## 4. CLI Code

### config.py — no validation of loaded config values

`get_cli_config()` and `get_agent_config()` return raw dicts from TOML parsing with no validation. A config with `volatile_mtime_threshold_days = "thirty"` or `url = 12345` would pass through and cause cryptic errors later.

**Recommendation:** Add basic type checking in `_load_config()` for critical fields (url must be string starting with `http`, threshold must be numeric, batch sizes must be positive int).

### scan.py — fresh_mtime_threshold_seconds not in config defaults

Line ~459 of scan.py reads `cfg.get("fresh_mtime_threshold_seconds", 60)` but this key is not documented in `config.py`'s `_DEFAULT` dict. The hardcoded fallback of 60 works, but users can't discover or configure it.

### exclusions.py — macOS iCloud path segment matching could false-positive

The macOS iCloud directory exclusion uses substring matching on path segments:
```python
if seg in path_lower:  # where seg = "/library/mail", etc.
```

This could false-positive on paths like `/mnt/mail_backup/` (contains `/mail`) on Darwin. The current excluded segments are specific enough (`/library/mail`, `/library/messages`, `/library/mobile documents`) that this is unlikely in practice, but the matching technique is fragile.

### normalize.py — normalize_query_path comment says "absolute inventory paths" but code says "./relative"

The docstring for `normalize_query_path` says:
> Bare names like 'users' or 'users/brian' [...] are treated as absolute inventory paths (i.e. 'users' → '/users').

But the code actually does:
```python
if p and not p.startswith(("/", "~", ".", os.sep)):
    p = "./" + p  # resolves relative to CWD
```

So `users` → `./users` → `{cwd}/users`, not `/users`. The docstring contradicts the code. The code behavior (resolving relative to CWD) is correct for CLI usage; the docstring needs updating.

### upgrade.py — fragile editable-install detection

`_is_editable()` does string matching on `direct_url.json`:
```python
return '"editable": true' in text
```

This will break if pip changes the JSON field ordering or escaping. Should use `json.loads()`.

---

## 5. Frontend Code

### Overlay sorting ignores user sort preference

When viewing subtree duplicate overlays (clicked "X uniq dup hashes"), results are sorted by hash → path → filename in a fixed order. The user's sort column selection (size, date, etc.) is ignored. `search-interaction-contract.md` marks this as `[TODO]` but it's a noticeable UX gap.

### Category filter can trap user in empty state

`availableCategories` is computed from filtered results. If the user selects "Images" and no images exist in the current view, available categories collapse to empty. The user cannot deselect "Images" because the filter UI shows no categories to toggle. The fix is to compute `availableCategories` from the unfiltered source data.

**Note:** The MEMORY.md already documents this: "`availableCategories` from UNFILTERED source to prevent collapse." If this is not actually implemented, it's a bug. If it is implemented, this analysis found a code path where it can still happen.

### Host selection doesn't invalidate tree cache

When `selectedHosts` changes, `buildRows()` recomputes from the existing cache. But dup metrics in the cache were computed for the previous host selection. The metrics (dup_count, dup_hash_count, other_hosts) are host-scoped, so switching hosts can show stale dup counts until the user navigates to a directory and triggers a fresh fetch.

### Dead API references

- `api.init()` endpoint is imported/defined but never called
- `api.duplicatesInSubtree()` mapped to `/files/duplicates-in-subtree` but appears unused in current frontend

These are harmless but add confusion.

---

## 6. Test Coverage Gaps

### Critical: `resolve_host()` had no tests (now fixed)

Added 9 tests in `tests/unit/test_resolve_host.py` covering:
case-insensitive matching, localhost/127.0.0.1 resolution, server-unreachable fallback,
unknown host passthrough, whitespace stripping, empty hosts list.

### Critical: `normalize_query_path()` had no tests (now fixed)

Added 8 tests in `tests/unit/test_normalize.py::TestNormalizeQueryPath` covering:
absolute paths, tilde expansion, dot/CWD resolution, trailing slashes,
bare names, root path, whitespace, double-dot parent.

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

### Tests added in this review

| File | Tests added | Coverage area |
|------|-------------|---------------|
| `tests/unit/test_resolve_host.py` | 9 tests (new file) | resolve_host() function |
| `tests/unit/test_normalize.py` | 8 tests | normalize_query_path() edge cases |
| `tests/unit/test_classify.py` | 10 tests | Edge cases: empty, unicode, spaces, dotfiles, camera RAW |
| `tests/unit/test_hash_utils.py` | 8 tests | Error scenarios: deleted file, directory, large content, callbacks, permissions |
| `tests/unit/test_commands_status.py` | 1 test | localhost resolution in status command |

---

## 7. Documentation Gaps

### search-interaction-contract.md has open TBDs

Three items marked `[TBD]` or `[TODO]` that affect current behavior:
1. Directory input behavior during overlay states (currently composable but undocumented)
2. Overlay group sorting contract (currently fixed-order, ignores user sort)
3. Regression checklist for search transitions (doesn't exist)

### duplicate-semantics.md doesn't cover aggregate staleness

The document defines semantics for dup counting and click-through but says nothing
about what happens when aggregates are stale or building. The frontend and server
each have ad-hoc handling. A "Freshness" section should define the contract.

### pyproject.toml version not bumped

Current version is `0.9.3`. The `resolve_host` feature and all other uncommitted
changes should bump the version before pushing, per project convention.

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

### Priority fixes

1. **Update `normalize_query_path` docstring** — contradicts actual code behavior
2. **Add aggregate staleness to `sift status`** — users can't see when dup stats are outdated
3. **Fix category filter trap** — verify `availableCategories` uses unfiltered source in all paths
4. **Overlay sorting** — either respect user sort preference or disable sort UI in overlay mode

### Priority tests to add

1. **Trim safety tests** — verify host isolation and path scoping on the destructive command
2. **Scan error recovery tests** — permission denied, file-disappears, disk full
3. **Server malformed input tests** — bad payloads, missing fields, oversized batches

### Things that are fine as-is

- `executemany()` existing in db.py (unused in production, only test conftest)
- Magic numbers in server config (reasonable defaults, low change frequency)
- Hardcoded extension lists in classify.py (comprehensive, easy to extend)
- Single RLock instead of reader-writer lock (correct for current scale)
- `host_stats` excluding skipped files (intentional, just needs clearer naming)
