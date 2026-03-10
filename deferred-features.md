# Deferred Features

Features intentionally left for future development.

Tracking note:

- This file is for intentionally deferred features only.
- Active behavior contracts live in `architecture-principles.md`, `duplicate-semantics.md`, and `search-interaction-contract.md`.
- If a deferred item starts affecting active semantics, add/update a tagged item (`[TBD]`, `[TODO]`, `[FUTURE]`) in the relevant contract doc and keep this file as a short pointer.

---

## `sift dups`
Duplicate analysis command: top wasted space, breakdown by category, host intersection/difference.

## `sift purge`
Safe interactive deletion of confirmed duplicates.

## `sift shell`
REPL with `cd`/`ls`/`find` against the inventory. Includes `rm` for removing inventory entries (not files).

## `sift dircomm`
Compare files in two directories, across hosts allowed, simiar to coreutils comm command. 

Example command:
dircomm -r HostA:/mnt/user/media HostB:/Users/Joe/media

Host: is optional and if not included, assume the local host. Resolve the host name similarly to the way the other sift coreutils like commands do, allow . for the current directory. 

in memory sort the hashes of files of dir1 and dir2, then compares the two sorted lists line-by-line and produces three tab-separated columns by default:

Column 1: files unique to DIR1

Column 2: files unique to DIR2

Column 3: files common to both

Not recursive on specified directories unless -r given on command line. 
Accept -23 to show files only in first or -13 to show files only in dir2 or -12 to show files common to both

Sorting and comparison to be done by the hashs of the files in the specified directories but the output should output, into the correct column(s), the files from the respective directory that carry the hash

---

## `/files` Duplicate Metadata Enrichment (Option C)

**Context / Motivation:**
The tree view (`/tree/children` + `/tree/dup-metrics`) carries duplicate semantics via
`dup_count`, `dup_hash_count`, and `other_hosts`. Search/hash overlays based on `/files`
currently do not return those fields, so frontend conversion code defaults duplicate counters
to zero. This can cause semantic drift in filtered views (for example, click-through from
"1 extra copy" where the source is known-duplicate, but overlay filtering logic treats rows
as non-dup unless separately inferred).

The goal is to make duplicate semantics explicit and consistent across tree mode and search
mode without reintroducing expensive query paths.

### Design goals

1. **Single source of truth for duplicate status in `/files` results**
   - Avoid frontend guesswork based on missing fields.
   - Make behavior of `Only dups` deterministic in search/hash overlays.

2. **Preserve fast default behavior**
   - Do not force expensive enrichment for every `/files` caller.
   - Keep lightweight paths available for high-frequency UI interactions.

3. **Correct host-scoped semantics**
   - For host-filtered queries, duplicate metadata should respect the selected host's view.
   - Cross-host indicators should remain explicit and not be conflated with same-host dup counts.

4. **Backwards-compatible rollout**
   - Additive API change first (new optional fields/flag), then frontend adoption.
   - No immediate contract break for existing clients.

### Proposed API shape

Add optional `/files` enrichment controlled by query parameter, e.g.:

- `dup_meta=1` (or `include_dup_meta=1`) to request duplicate metadata.

Candidate response additions per `FileEntry` row:

- `is_duplicate_for_host: bool`
- `same_host_copy_count: int | null` (or effective copy count)
- `is_cross_host_duplicate: bool`

Alternative minimal contract:

- `dup_flags: { same_host: bool, cross_host: bool }`

The minimal contract is preferred for payload size and simplicity.

### Query/performance strategy (critical)

Do **not** compute per-row duplicate metadata via raw `files` self-joins on every request.
Use pre-aggregated tables where available:

- `host_hash_stats` for host-scoped duplicate checks (`copy_count_effective > 1`)
- `hash_stats` for global checks when needed

For `host`-scoped `/files` requests, enrichment should be implemented as lightweight joins to
`host_hash_stats` keyed by `(host, hash)`. Avoid fallback to full-table `GROUP BY hash` unless
explicitly allowed and guarded.

### Risk management requirements

1. **No regression in lock behavior**
   - Any new enrichment path must avoid recreating multi-minute lock contention patterns.
   - Validate with mixed-load tests (`/hosts`, `/stats/overview`, tree endpoints in parallel).

2. **Feature-flagged rollout**
   - Gate enrichment behind request param and/or server flag initially.
   - Allow immediate rollback to current behavior if latency spikes are observed.

3. **Budgeted performance checks**
   - Track p50/p95/max on representative large paths and hosts.
   - Specifically test host-filtered duplicate lookups and hash-click overlay workloads.

4. ~~**Cache/aggregation freshness behavior**~~ — DONE.
   Maintenance worker now enabled by default; `sift status` shows staleness;
   server logs job start/completion. See `duplicate-semantics.md` §Freshness.

### Frontend semantics guidance

- In hash-result overlays, if results originate from an explicitly duplicate-qualified action
  (e.g. click on "1 extra copy"), the UI should not hide those rows due to absent duplicate
  metadata.
- `Only dups` should continue to mean "show rows with matching hashes that are duplicates under
  current semantics"; it should not require toggling state changes for hash-overlay behavior.
- Click-through from a file row should continue to include the clicked source row even when it is
  non-duplicate under current filters.

### Validation checklist

- `/files` with enrichment enabled returns stable duplicate flags for same-host and cross-host cases.
- Frontend hash overlays no longer regress to empty results for known duplicate click-through flows.
- No measurable DB regression under mixed UI + CLI load on production-scale datasets.
- No reintroduction of lock-fanout completion patterns in server logs.

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

## Host-Scoped Directory Search Index (for Tree View)

**Context:** Tree View directory search currently queries a global directory index and then tries to expand matches in the selected host set. With multiple hosts selected, common terms (for example `Documents`) can return many global matches that do not map cleanly to visible branches for the current selection.

**Why defer:** The current UX can be improved cheaply with better ranking and a higher limit, but true host-aware relevance requires schema and maintenance changes.

### Desired behavior

1. Directory search results are scoped to selected hosts by default.
2. Matches are ranked so basename/segment matches surface first (for example exact `Documents` before deep incidental matches).
3. Tree expansion uses host-relevant matches, reducing "typed a valid term but nothing obvious happened" moments.

### Proposed backend shape

Add a host-scoped aggregate table (or equivalent materialized structure), for example:

- `directory_index_by_host(host, dir_path, dir_display, updated_at)`

Refresh strategy:

- On scan ingest for host `H`, enqueue/refresh only `directory_index_by_host` for `H`.
- Keep existing global `directory_index` for non-host-scoped use cases and backward compatibility.

Endpoint strategy (additive):

- Extend `GET /directories` with optional `hosts` query param (comma-separated).
- If `hosts` is present, query host-scoped index with `WHERE host IN (...)` and return de-duplicated paths.
- Keep old behavior when `hosts` is absent.

### Frontend changes when this is implemented

1. In Tree View directory search, pass selected hosts to `/directories`.
2. Keep mode-specific behavior already defined:
   - Tree View: search drives path expansion.
   - List View: search is path text filter (`path_contains`).

### Performance / lock-safety requirements

1. No live full-table fallback on large inventories for host-scoped directory queries.
2. Cache key must include normalized host-set + query + limit.
3. Maintenance jobs should update host-scoped directory index incrementally per host.
4. Validate no reintroduction of long lock hold times under mixed `/hosts`, tree, and stats traffic.

### Rollout notes

1. Land schema + refresh path first.
2. Add host-aware query path behind optional `hosts` param.
3. Wire frontend Tree View to pass selected hosts.
4. Keep global path as fallback for compatibility and staged rollout.

---

## Preserve Tree State on Filter/Host Changes

**Context:** Changing `minDupSize` currently collapses the tree (expanded directories reset), which interrupts navigation and forces users back to top-level. Host selection changes can similarly feel disruptive when the user is deep in the tree.

**Desired UX semantics:**
- `minDupSize` change: preserve expanded tree state; recompute dup metrics/highlighting in place.
- Host shift-click add/remove: preserve expanded tree state; recompute dup-related values (`dup_count`, `other_hosts`, extra copies).
- Plain host click (single-host select):
  - If clicked host was already part of the previous selection: preserve expansion.
  - If clicked host was not previously selected: reset expansion (intentional context switch).

**Implementation outline (frontend):**
1. In `frontend/src/App.jsx`, stop clearing `expandedPaths`/`dupAutoExpanded` on `minDupSize` change.
2. Replace hard cache bust + collapse with targeted refresh for currently visible/open paths (current path + expanded paths), requesting dup metrics for new threshold.
3. Add host-selection transition logic using previous selection ref:
   - Detect whether plain-click selected a host already in prior selection.
   - Apply preserve-vs-reset behavior per UX semantics above.
4. Keep explicit resets for explicit reset/navigation actions (`Reset`, path root/navigation changes).
5. Add safety cap/batching when many directories are expanded to avoid request bursts.

**Risks / considerations:**
- Larger expanded trees can trigger many refresh requests; cap path fanout and batch.
- Ensure no stale dup metrics race by honoring current threshold/selection refs before applying async responses.

**Validation checklist:**
- Deep tree remains open when changing `minDupSize`.
- Shift add/remove host updates duplicate counts/highlighting without collapsing.
- Plain click to previously unselected host resets expansion.
- Plain click to already-selected host keeps expansion.
- `onlyDups`, pinned views, and subtree dup views remain consistent.

---

## APFS Dataless / Cloud-Stub File Handling

## Filename Whitespace Visualization

**Context:** Some real inventories include filenames with leading/trailing or repeated internal spaces. These can make sort order look "wrong" to users (for example leading-space files appearing first) and are hard to visually spot in proportional UI text.

**Deferred UX enhancement:** Add optional filename whitespace visualization in the table row name cell:

- Render visible-space markers with subtle tint (for example light dot/space tint) for all whitespace characters in displayed filenames.
- Preserve true underlying filename bytes (display-only transform).
- Prefer mode-agnostic behavior (Tree and List), with a toggle if visual noise is a concern.

**Why this helps:**

1. Clarifies seemingly odd sort positions without changing filesystem semantics.
2. Reveals trailing spaces and double-spaces that are otherwise easy to miss.
3. Reduces user confusion during dedupe/manual cleanup workflows.

**Implementation notes (future):**

- Keep clipboard/copy-path behavior unchanged (raw filename/path).
- Ensure marker rendering does not break truncation/ellipsis performance.
- Consider monospaced fallback or partial monospaced spans only for markerized filename text.

---

**Context / Why this matters:**
`sift scan` is extremely slow on macOS machines with large Apple Mail libraries or iCloud Drive
folders. The cause: `.partial.emlx` and APFS "dataless" stub files — files that appear to have
content (`st_size > 0`) but have no local disk blocks (`st_blocks == 0`). Reading them triggers
an on-demand download from Apple's servers, turning a microsecond hash into a multi-second stall
per file. A Mail library can contain hundreds of thousands of such files.

**Detection methods:**
- **General (APFS cloud stubs):** `stat_result.st_blocks == 0` — reliable on APFS for any file
  that has been evicted to iCloud (Drive, Photos, Mail, etc.). macOS-only; no-op on Linux/Windows.
- **Specific (Mail partials):** `.partial.emlx` extension — Apple Mail partial downloads. May have
  some blocks allocated but content is incomplete; hash would be meaningless.

**Three categories of "cloud" files (different treatment):**
1. **APFS dataless stubs (`st_blocks == 0`):** Bytes not on local disk. Record with
   `skipped_reason="macos_dataless"`, DO NOT hash. These don't count as local copies for LAN
   dedup purposes — they physically don't exist on the LAN.
2. **Partial files (`.partial.emlx`):** Some local bytes but incomplete. Same treatment:
   record, skip hash, `skipped_reason="macos_dataless"`.
3. **"Optimized" files that ARE locally present:** Photos originals on the MacBook, Documents
   actively in use — these have `st_blocks > 0` even when iCloud-backed. The `st_blocks` check
   correctly allows these through for normal hashing. Do NOT exclude them.

**Why NOT hash dataless/partial files:**
- Hash is meaningless for dedup — partial content never matches a full copy of the same file
- Reading triggers a slow iCloud/Mail server network download
- `.partial.emlx` is transient — gets replaced with full `.emlx` when fully fetched, making
  stored hash immediately stale
- `st_blocks == 0` files have zero bytes on local SSD — nothing to hash

**Why still RECORD them (don't skip entirely):**
- Inventory visibility: useful to know a machine "has" 200k Mail messages even if partial
- `skipped_reason="macos_dataless"` distinguishes "not hashed because cloud" from permission
  errors or volatile files — important for future analysis
- Leaves door open for future cloud-dup features without re-scanning

**The "cloud duplicate" philosophical question:**
Today sift answers: "same bytes exist on multiple LAN hosts." A cloud dup would mean "same
bytes exist on a LAN host AND in iCloud." This is a fundamentally different relationship:
- Different tooling needed (Apple CloudKit APIs, not filesystem reads)
- Out of scope for core LAN dedup mission
- Not addressable via `st_blocks` detection alone
- **Deferred indefinitely — likely out of scope entirely**

**Photos library nuance (deferred):**
macOS Photos can store "optimized" (lower-res) thumbnails locally while originals live in
iCloud. The thumbnail IS a locally-allocated file (`st_blocks > 0`) but is not the original.
Detecting this requires inspecting xattrs or the Photos library database — complex, out of
scope for the initial fix. The `st_blocks` approach handles the zero-block case correctly
and won't interfere with locally-present Photos originals.

**Recommended implementation (near term):**

In `sift/commands/scan.py`, after `stat_result = os.stat(sp)` and before the hash check, add:

```python
# macOS: skip APFS dataless stubs (cloud-evicted files have no local blocks)
if source_os == "darwin" and stat_result.st_blocks == 0:
    upsert_records.append(_make_record(
        ..., hash_val=None, skipped_reason="macos_dataless", ...
    ))
    stats["files_skipped"] += 1
    continue
```

Also route `.partial.emlx` files to the same `skipped_reason="macos_dataless"` path
(record in inventory, skip hash) rather than excluding them entirely.

Note: `st_blocks` is in 512-byte units on macOS. `st_blocks == 0` means truly no allocated
blocks. Sparse files edge case not worth special-casing here.

**Files to modify:**
- `sift/commands/scan.py` — main scan loop, after stat(), before hash check
- Verify `get_source_os()` in `sift/normalize.py` returns `"darwin"` on macOS

---

## Config-driven `db_path`

Add `db_path` setting to `~/.sift.config` so users can relocate the database without
setting the `SIFT_DB_PATH` environment variable. Resolution order would be:
`SIFT_DB_PATH` env → `db_path` in config → `~/.sift.duckdb` default.

Relevant code: `server/db.py:get_db_path()`.

---

## `sift server --daemon` / `sift server stop`

Background server management for non-Docker installs (e.g. Windows single-PC use).

- `sift server --daemon` — start server in background, write PID to `~/.sift.pid`
- `sift server stop` — read PID file, kill the process, clean up

**Constraint:** avoid platform-specific code paths (no `os.fork()`). Use
`subprocess.Popen` on all platforms so there's one implementation.

Today's workflow is fine for MVP: run `sift server` in a terminal, Ctrl+C to stop.
Docker/Unraid is unaffected — the container runs in foreground as normal.

---

## Scan Cache Performance / Data Store Optimization

**Context:** At scan startup, `GET /files/cache` fetches every previously-indexed file (path +
mtime + size) for the scanned host/root as a single response. On large roots this can be 10MB+
of JSON and cause a 30–60s apparent freeze before scanning begins.

### Null-hash retry prefetch limitations (new)

`sift scan --null-hash-retry` currently uses `GET /files` (no server contract changes) to
prefetch candidate paths with `hash IS NULL` under the active host/root. This has two important
limitations that should be addressed in future work:

1. **Single-call cap risk**
   - Current prefetch is a single call with a large `limit` (currently 1,000,000).
   - If matching rows exceed the limit, only the first slice (ordered by path) is seen.
   - Because `/files` currently has no offset/cursor, lower limits do **not** eventually cover
     the full candidate set across runs; tail rows can be permanently missed.

2. **Startup latency on large hosts**
   - Example observed production behavior: one prefetch call returned ~849k rows and took ~13.6s.
   - This is acceptable as an explicit opt-in mode, but should not become the default path.

3. **Drive-scoped gap on multi-drive hosts**
   - `/files` has host/path filters but no drive filter in the public contract.
   - Client currently skips null-hash prefetch in drive-scoped scans to avoid over-broad retries.

**Deferred improvements to consider:**

- Add pagination to `/files` (`offset`/cursor) so client prefetch can walk the full set safely.
- Add drive filter support to `/files` for precise Windows/multi-drive scoping.
- Add a lightweight retry-hint field to cache endpoints (preferred long-term), avoiding heavyweight
  prefetch entirely while keeping aggregate-first/lock-safe behavior.

### Null-hash retry semantics (deferred target)

**Conversation summary / intent:**

- Current cache-driven scan logic can leave some `hash = NULL` rows un-retried when `mtime` and
  `size` are unchanged, because cache payload lacks per-row null-hash/skip-reason context.
- A temporary explicit mode (`--null-hash-retry`) was added client-side using `/files` prefetch,
  but this is intentionally not the long-term architecture because of startup latency and limit
  coverage constraints described above.

**Desired long-term behavior:**

- Re-attempt hashing for `hash IS NULL` rows **unless** the row was intentionally skipped.
- Keep per-file decision lightweight in the hot scan loop (no expensive fallback queries).

**Intentional skip reasons (current candidate set):**

- `sparse_file`
- `macos_dataless`
- `windows_cloud_placeholder`
- `volatile_active`
- `recently_modified`

**Retry-eligible null-hash reasons (examples):**

- `permission_error`
- generic read/I/O failures (transient conditions)
- missing/legacy/null `skipped_reason` where null hash should be retried

**Preferred API enhancement (future):**

- Add a compact retry hint on cache endpoints (for example `retry_hash`), or equivalent metadata
  that enables this rule without heavyweight client prefetch.
- Ensure hint is derived from existing row fields (`hash`, `skipped_reason`) and keeps aggregate-
  first/low-lock principles.

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

## Network Filesystem Exclusion

**Status**: Implemented (v0.7.2+). All network mounts are excluded by default.

### Problem
Running `sift scan /` or `sift scan /mnt` on a host with NFS/SMB mounts causes:
stale NFS hangs, massive unintended network scans, false cross-host duplicates,
and LAN bandwidth saturation.

### What was implemented
- Mount registry built once at scan startup (cached via `@lru_cache`)
- Scan root on a network FS → hard error + exit
- Network subdirectories encountered during walk → warning to stderr + skip
- Precount mirrors the same check for consistency

### Detection by platform
- **Linux**: parse `/proc/mounts` (field[1]=mount point, field[2]=fstype)
- **macOS**: parse `mount` command output (regex for `on <path> (<fstype>,`)
- **Windows**: `kernel32.GetDriveTypeW()` per drive letter (value 4 = DRIVE_REMOTE)

### Excluded filesystem types
`nfs`, `nfs4`, `cifs`, `smbfs`, `afp`, `afs`, `ncpfs`, `9p`,
`fuse.sshfs`, `fuse.rclone`, `fuse.s3fs`, `fuse.gcsfuse`, `fuse.nfs`

### Local FUSE — NOT excluded
`fuse.mergerfs`, `fuse.unionfs`, `fuse.ntfs-3g`, `zfs-fuse`, and any
unlisted FUSE type (safe default: assume local). Critical for Unraid where
`/mnt/user` is `fuse.mergerfs`.

### Future consideration
- `--include-network` flag if users explicitly want to scan network mounts
- Per-mount overrides in `~/.sift.config`
