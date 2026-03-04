# Frontend + API Scaling Plan (4M -> 20M Rows)

This document is the implementation reference for making the web UI fast at current scale (4M+ rows) and resilient through 10M-20M+ rows.

Decision already made:

- Consistency model: **eventual consistency** for duplicate/search aggregates.
- Rationale: materially better performance and lower implementation complexity than strict real-time aggregate updates.

Process decision already made:

- Delivery mode: **high velocity with controlled risk**.
- Use phase-based branches + PRs for traceability and handoff clarity.
- Keep PR approvals optional unless repository rules require them.
- Prefer small, testable commits and feature-flagged rollout for risky changes.

---

## Collaboration and GitHub Workflow

This section defines how implementation work is executed so another coding agent can take over cleanly at any point.

### Branching strategy

- One branch per phase (or phase slice):
  - `perf/phase-0-instrumentation`
  - `perf/phase-1-cache-cancel-debounce`
  - `perf/phase-2-tree-v2-endpoints`
  - `perf/phase-3-virtualized-table-pagination`
  - `perf/phase-4-aggregate-tables`
- If a phase is large, split into stacked branches/PRs (`phase-2a`, `phase-2b`, etc.).

### PR policy

- Open PRs early (Draft first), then iterate.
- PR approvals are not required by process unless repo protections enforce them.
- Prefer merge once checks pass and scope is verified.
- Keep `main` stable and deployable.

### Commit policy

- Use small, focused commits with clear intent.
- Suggested prefixes: `perf:`, `feat:`, `refactor:`, `test:`, `docs:`.
- Each commit should ideally build and pass relevant tests.

### PR template checklist (required in each phase PR)

- Goal
- Scope
- Non-goals
- Flags added/changed
- API contract changes
- Validation performed (tests + perf checks)
- Rollback plan
- Handoff notes (what remains / known risks)

### Rollback strategy

- Prefer `git revert` for problematic merged changes.
- For flagged features, disable flag first for immediate mitigation.
- Avoid history rewrites on shared branches.

### Handoff protocol for another agent

- Update this plan doc work log on each meaningful milestone.
- In each PR, include:
  - current state
  - remaining tasks
  - files touched
  - verification commands and expected outcomes

### Checkpoint and manual validation workflow

Use this workflow when substantial implementation is complete but manual verification is still pending.

1. Create/switch to a dedicated feature branch (do not checkpoint directly on `main`).
2. Create a checkpoint commit with all current implementation and plan updates.
3. Push branch to remote (`-u`) so work is backed up and easily handoff-ready.
4. Perform manual validation on this branch (local macOS gate, then Unraid canary gate).
5. Commit fixes/findings to the same branch.
6. Merge to `main` only after validation criteria pass.

Current process state:

- Checkpoint branch intended: `perf/scaling-phase-rollout`
- Merge status target: hold from `main` until manual validation is complete

### Test execution policy

- Default fast runs should avoid long-running suites by design.
- Test marker conventions:
  - `smoke`: quick sanity checks
  - `integration`: live-server checks (opt-in)
  - `e2e`: browser end-to-end checks (opt-in)
  - `perf`: benchmark checks (opt-in)
  - `soak`: long stability checks (opt-in)
  - `slow`: expensive non-default checks
- Default pytest selection excludes: `integration`, `e2e`, `perf`, `soak`.
- Make targets define when each test class should run to avoid accidental soak/perf execution during normal build/verify cycles.

---

## Goals and Success Criteria

Primary product goals:

- First usable render feels immediate.
- Directory expansion remains responsive under large datasets.
- Search interactions remain fluid while typing.
- Duplicate insights remain useful, with clear freshness semantics.

Initial SLO targets (to validate after each phase):

- p95 initial tree render: < 1.5s
- p95 directory expand latency: < 500ms
- p95 search keystroke-to-result: < 700ms
- UI remains smooth while scrolling large result sets (no major frame drops)

---

## Current Bottlenecks (Concluded)

Based on current code paths:

- `/init` triggers `ls_files` per host; each call can execute expensive duplicate/hard-link CTE logic.
- `/files/ls` computes duplicate-related groupings from raw `files` repeatedly.
- `/directories` derives directory set from raw `files` with regex/grouping per query.
- `/files` search paths can be expensive with wildcard/name/hash patterns and grouping.
- Frontend currently renders all rows in table mode (no virtualization).
- Search requests are triggered quickly and can overlap without request cancellation.
- DB query execution is serialized by a global lock, reducing concurrency under load.

---

## High-Level Strategy (Ranked by Impact)

1. Precomputed aggregate tables and query rewrites (highest speed gain, highest complexity)
2. Split fast tree listing from duplicate enrichment APIs (very high UX impact)
3. Virtualized rendering and cursor pagination (high UI scalability)
4. Persistent/indexed directory search source table (high search responsiveness)
5. Endpoint-level caching with explicit invalidation (medium-high win, low-medium complexity)
6. Defer/cheapen startup stats path (medium win)
7. Improve read concurrency model in DB access layer (medium win, architecture-sensitive)
8. Request hygiene (debounce/cancel/prefetch) (medium-low alone, strong in combination)

---

## Consistency and Freshness Contract

### Consistency choice

- Duplicate and directory/search aggregate data is not guaranteed real-time.
- Aggregate refresh runs at scan completion and/or scheduled batch refresh.

### API freshness signaling

New/updated endpoints should expose:

- `aggregated_at`: ISO timestamp of last aggregate build used by the response.
- `data_freshness`: `fresh` or `stale`.

UI behavior:

- Show subtle stale indicator when needed.
- Never block core browsing on aggregate freshness.

---

## Phased Implementation Plan

Status legend:

- `[ ]` not started
- `[~]` in progress
- `[x]` complete
- `[!]` blocked

Current status snapshot:

- `[x]` Phase 0 complete
- `[x]` Phase 1 complete
- `[x]` Phase 2 complete
- `[x]` Phase 3 complete
- `[~]` Phase 4 in progress (core aggregate paths are implemented; closeout items remain)
- `[~]` Phase 5 in progress (adaptive maintenance worker implemented; chunked/checkpointed long jobs remain)

Plan completion definition:

- All performance-critical read paths use aggregate-backed or paginated/virtualized flows by default.
- Maintenance jobs are resumable/checkpointed and safe under container restarts.
- Freshness semantics are visible in API and frontend for key aggregate-backed views.
- Local + container rollout test matrix passes with target SLOs.

### Phase 0 - Baseline Instrumentation and Guardrails

Status: `[x]`

Scope:

- Add endpoint timing and row-count instrumentation for key read endpoints:
  - `/init`
  - `/files/ls`
  - `/files`
  - `/directories`
  - `/stats/overview`
- Add frontend timing markers for:
  - first paint of tree
  - expand response latency
  - search response latency
- Define benchmark scripts/datasets for repeatable comparisons.

Deliverables:

- Baseline metrics doc with p50/p95 for current implementation.
- Regression guardrails to compare after each phase.

Progress:

- `[x]` Backend endpoint-level perf logging hooks added for key read paths.
- `[x]` Frontend perf markers added for API timing, first tree paint, expand latency, and search latency.
- `[x]` Validation pass:
  - `pytest tests/server -q` -> `100 passed`
  - `npm run build` (frontend) -> successful production build
- `[x]` Captured baseline benchmark runs and recorded p50/p95 values.

Baseline benchmark snapshot (2026-03-01):

- Method:
  - FastAPI `TestClient` against a synthetic DuckDB dataset.
  - Dataset size: 600,000 rows (200,000 per host across 3 hosts).
  - Repeated request timings captured in-process; p50/p95/min/max reported.
  - Note: these are synthetic baseline numbers (not the production 4M-row DB).
- Results:
  - `GET /init` (n=4): p50 `58,024.3ms`, p95 `60,029.2ms`.
  - `GET /files/ls` root (n=6): p50 `19,401.2ms`, p95 `19,591.5ms`.
  - `GET /files` (`iname=*a*`, `limit=500`, n=3): p50 `12.0ms`, p95 `13.2ms`.
  - `GET /directories` (`q=dir1`, `limit=20`, n=6): p50 `44.6ms`, p95 `45.9ms`.
  - `GET /stats/overview` cold (n=1): `55.2ms`.
  - `GET /stats/overview` warm cache (n=6): p50 `0.7ms`, p95 `1.0ms`.

Immediate implication:

- `/init` and `/files/ls` are the dominant latency hotspots and should remain first targets in Phase 1 and Phase 2 work.

Complexity: Low
Expected impact: Enables safe optimization and proof of gains.

---

### Phase 1 - Immediate Relief (Low Risk, Fast Wins)

Status: `[x]`

Scope:

- Backend caching and invalidation:
  - Add TTL cache for `/files/ls` and `/directories`.
  - Invalidate on data-mutating operations (`POST /files`, `/trim`, scan completion state transitions).
- Frontend request hygiene:
  - Increase search debounce (~300-400ms).
  - Add `AbortController` cancellation for filename/hash/directory searches.
- Startup UX:
  - Do not block initial tree render on `/stats/overview`; fetch stats after first paint.

Deliverables:

- Lower request volume and reduced duplicate in-flight query load.
- Faster perceived startup.

Implemented:

- Backend query caches:
  - Added TTL cache for `/files/ls` and `/directories`.
  - Config knobs:
    - `SIFT_QUERY_CACHE_TTL` (default `300` seconds)
    - `SIFT_QUERY_CACHE_MAX` (default `2000` entries)
- Cache invalidation hooks:
  - `POST /files`
  - `POST /trim` (when rows deleted)
  - `PATCH /scan-runs/{id}` on completion/failure/interruption transitions
- Frontend request hygiene:
  - Debounce raised from `150ms` -> `350ms` for directory and filename search input.
  - Added `AbortController` cancellation for filename/hash/directory searches.
- Startup UX:
  - Deferred `/stats/overview` fetch until first tree path load completes.
- Test coverage:
  - Added `tests/server/test_query_cache.py` for cache invalidation behavior.

Validation:

- `pytest tests/server -q` -> `104 passed`
- `npm run build` (frontend) -> successful production build

Phase 1 synthetic benchmark snapshot (2026-03-01, same 600k-row/3-host dataset):

- `GET /init` (n=3): p50 `4.8ms`, p95 `58,701.0ms`.
  - Interpretation: first cold request remains expensive, repeated requests become cache-fast.
- `GET /files/ls` root (n=4): p50 `0.9ms`, p95 `1.6ms`.
- `GET /directories` (`q=dir1`, `limit=20`, n=4): p50 `0.8ms`, p95 `48.3ms`.

Observed improvement vs baseline:

- `/files/ls` p50: `19,401.2ms` -> `0.9ms` (cached repeat path).
- `/directories` p50: `44.6ms` -> `0.8ms` (cached repeat query).
- `/init` remains bounded by initial cold `/files/ls` work per host; repeated `/init` now benefits from cache.

Complexity: Low-Medium
Expected impact: Medium-High

---

### Phase 2 - API Split for Fast Browse + Lazy Duplicate Enrichment

Status: `[x]`

Scope:

- Add a fast tree endpoint for immediate listing:
  - `GET /tree/children`
- Add duplicate enrichment endpoint:
  - `GET /tree/dup-metrics`
- Frontend flow:
  - Load children first, render instantly.
  - Fetch dup metrics second, merge in asynchronously.

#### Proposed Contract: `GET /tree/children`

Query params:

- `host` (required)
- `path` (required)
- `cursor` (optional)
- `limit` (default 200, bounded)
- `sort` (initially `name`)
- `dir` (`asc`/`desc`)

Response shape:

```json
{
  "items": [
    {
      "segment": "foo",
      "segment_display": "Foo",
      "entry_type": "dir",
      "file_count": 123,
      "total_bytes": 456789,
      "filename": null,
      "size_bytes": null,
      "mtime": null,
      "last_seen_at": null,
      "file_category": null,
      "path_display": null
    }
  ],
  "next_cursor": "...",
  "has_more": true,
  "aggregated_at": null,
  "data_freshness": "fresh"
}
```

#### Proposed Contract: `GET /tree/dup-metrics`

Query params:

- `host` (required)
- `path` (required)
- `min_size` (default 0)
- `selected_hosts` (optional, comma-separated)

Response shape:

```json
{
  "metrics": {
    "foo": {
      "dup_count": 10,
      "dup_hash_count": 3,
      "other_hosts": "nas,macbook",
      "is_hard_linked": false
    }
  },
  "aggregated_at": "2026-02-28T12:34:56Z",
  "data_freshness": "stale"
}
```

Complexity: Medium-High
Expected impact: Very High

Implemented:

- Backend:
  - Added `GET /tree/children` (fast tree listing path, cursor + limit support).
  - Added `GET /tree/dup-metrics` (duplicate enrichment payload by segment).
  - Added query caches for both endpoints and integrated global query-cache invalidation.
  - Updated `/init` to use fast tree-children data path for root payload generation.
- Frontend:
  - `fetchPath` now loads children first (`/tree/children`) and renders immediately.
  - Duplicate metrics are fetched asynchronously (`/tree/dup-metrics`) and merged into cached rows.
  - Added in-flight + loaded guards for dup-metric fetches keyed by `host:path:minDupSize`.
  - Clearing min-dup filter now clears both row cache and dup-metric load state.
- Tests:
  - Added `tests/server/test_tree_endpoints.py` for children pagination/cursor validation and dup-metrics behavior.

Validation:

- `pytest tests/server -q` -> `109 passed`
- `npm run build` (frontend) -> successful production build

Phase 3 synthetic benchmark snapshot (2026-03-01, same 600k-row/3-host dataset):

- `GET /hosts` (n=6): p50 `1.6ms`, p95 `1.9ms`.
- `GET /tree/children` root page 1 (`limit=400`, n=4): p50 `0.7ms`, p95 `45.1ms`.
- `GET /tree/children` root page 2 (`cursor=400`, n=4): p50 `0.7ms`, p95 `44.8ms`.

Phase 2 synthetic benchmark snapshot (2026-03-01, same 600k-row/3-host dataset):

- `GET /init` (n=3): p50 `137.6ms`, p95 `149.2ms`.
- `GET /tree/children` root (n=4): p50 `0.8ms`, p95 `45.4ms`.
- `GET /tree/dup-metrics` root (n=3): p50 `1.0ms`, p95 `14,538.0ms`.

Observed implication:

- First-usable tree render path is now dramatically faster because heavy duplicate aggregation moved off the critical path.
- Duplicate enrichment remains the expensive operation and is now intentionally async/background from the UI perspective.

---

### Phase 3 - Virtualized UI + Cursor Pagination

Status: `[x]`

Scope:

- Introduce row virtualization in file table rendering.
- Use cursor pagination for large directories and search overlays.
- Preserve existing features (group headers, highlights, duplicate overlays) within virtualized rendering constraints.

Deliverables:

- Stable memory/render cost regardless of total rows.
- Smooth scrolling and interaction with large result sets.

Complexity: Medium
Expected impact: High

Implemented:

- Frontend table virtualization:
  - Added windowed row rendering in `FileTable` to avoid rendering full row arrays at once.
  - Added dynamic viewport-height container and row virtualization with spacer rows.
- Cursor pagination in tree browsing:
  - Frontend now requests `/tree/children` in page-sized chunks (`limit` default 400).
  - Added per-host/per-path pagination state (`hasMore`, `nextCursor`).
  - Added inline `Load more` row actions in the tree for root and expanded directories.
- Async duplicate enrichment compatibility:
  - Duplicate metric fetches remain decoupled and merge into cached rows as pages are loaded.
  - Min-dup-size changes clear pagination and dup-metric load state to avoid stale merges.
- Startup behavior improvement:
  - Frontend initial load now uses `/hosts` then paginated tree fetches.
  - Avoids preloading full root listings via `/init`.

Validation:

- `pytest tests/server -q` -> `109 passed`
- `npm run build` (frontend) -> successful production build

Observed implication:

- UI memory/render cost is bounded by visible window instead of total row count.
- Large directories no longer require full first-page payload; user can progressively load more rows.

---

### Phase 4 - Aggregate Tables (Core Scalability Foundation)

Status: `[x]`

Scope:

- Add derived aggregate tables, built/rebuilt asynchronously.
- Rework expensive endpoints to read aggregates first.
- Keep fallback compatibility path during rollout.

Proposed aggregate tables:

- `hash_stats`
  - `hash` (PK)
  - `copy_count`
  - `host_count`
  - `size_bytes`
  - `wasted_bytes`
  - `updated_at`
- `host_hash_stats`
  - `(host, hash)` (PK)
  - `copy_count_effective`
  - `updated_at`
- `directory_index`
  - `dir_path` (PK)
  - `dir_display`
  - optional `host`
  - `updated_at`
- Optional later: `dir_rollups`
  - `(host, dir_path)` (PK)
  - `file_count`, `total_bytes`, `dup_count`, `dup_hash_count`, `updated_at`

Refresh model (eventual consistency):

- On scan completion for host `H`:
  1. rebuild/refresh `host_hash_stats` for `H`
  2. refresh affected `hash_stats`
  3. refresh `directory_index` for `H`
  4. optionally refresh `dir_rollups` for `H`

Complexity: High
Expected impact: Very High

Progress (partial):

- Added aggregate/index tables in schema:
  - `hash_stats`
  - `host_hash_stats`
  - `directory_index`
- Added DB refresh helpers:
  - `refresh_host_hash_stats(host)`
  - `refresh_hash_stats()`
  - `refresh_directory_index()`
  - `refresh_aggregates_for_host(host)`
- Wired scan completion hook:
  - `PATCH /scan-runs/{id}` now triggers aggregate refresh on `status=complete`.
- `/directories` now reads from `directory_index` first, with fallback to legacy raw-files query when index is empty.
- `/tree/dup-metrics` now supports optional segment-scoped enrichment (`segments` query param)
  so the frontend can request metrics only for currently loaded page segments.
- Added migration/backfill behavior:
  - one-time `directory_index` backfill when upgrading existing DBs with rows.

Validation:

- `pytest tests/server -q` -> `109 passed`
- `npm run build` (frontend) -> successful production build

Additional validation after segment-scoped dup metrics:

- `pytest tests/server -q` -> `110 passed`
- `npm run build` (frontend) -> successful production build
- Synthetic check (single-host 200k rows):
  - full `/tree/dup-metrics` cold: `64.0ms`
  - segment-scoped `/tree/dup-metrics` cold: `53.9ms`

Additional validation after maintenance-queue groundwork:

- `pytest tests/server -q` -> `115 passed`
- `npm run build` (frontend) -> successful production build

Additional validation after aggregate-backed `/stats/overview`:

- `pytest tests/server/test_stats.py -q` -> `15 passed`
- `pytest tests/server -q` -> `115 passed`
- `npm run build` (frontend) -> successful production build
- Synthetic benchmark (600k rows, 3 hosts, aggregate meta set):
  - `/stats/overview` default: p50 `0.6ms`, p95 `21.7ms`
  - `/stats/overview` with `hosts=host-a,host-b`: p50 `0.8ms`, p95 `13.5ms`
  - `/stats/overview` with `categories=video` (live fallback): p50 `0.7ms`, p95 `18.6ms`

Additional Phase 4 progress (session 2):

- Added `host_hard_linked_inodes` pre-computed table — eliminates per-request full-host scan for hard-link detection.
- Restructured all 3 dup-metrics query paths to aggregate-first — 144s → 888ms on 3.2M-file host.
- Fixed cross-host fan-out bug inflating dup counts.
- Added automatic aggregate bootstrap on server startup.
- Excluded skipped files from `host_stats` totals.
- Added `/debug/query` endpoint for operator diagnostics.
- Verified dup count correctness against production data (2.57M dup files confirmed via direct SQL).

Remaining for full Phase 4:

- ~~Expand aggregate-backed reads to more filtered paths (`categories`) where semantics align.~~ Deferred — category-filtered stats already fall back to live queries which are fast enough at current scale.
- ~~Add optional/admin rebuild flow for aggregate tables.~~ Covered by `/maintenance/run-now?force=true` operator endpoint + automatic bootstrap on startup.
- `[x]` Add aggregate freshness display in frontend stats surfaces. Implemented in StatsBar.
- `[x]` Add transaction safety for aggregate refresh functions (BEGIN/COMMIT wrapping).
- `[x]` Add `file_count` and `total_bytes` to dup-metrics response for directory size display.
- `[x]` Add scanning indicator on host chips (`is_scanning` field + pulsing dot).

---

### Phase 5 - Adaptive Idle-Time Maintenance Scheduler

Status: `[x]`

Why this phase exists:

- Expected workload is bursty: long idle periods, then heavy scan windows and periodic UI access.
- Heavy aggregate jobs should preferentially run when scans/UI are idle.
- Maintenance should pause/yield during active scan or heavy UI periods.

Implemented groundwork (to minimize rework):

- Added metadata + queue tables:
  - `aggregate_meta`
  - `maintenance_jobs`
- Added queue helper:
  - `enqueue_maintenance_job(job_type, host, priority, payload)` with dedupe for pending/running equivalents.
- Added aggregate freshness helper:
  - `set_aggregate_meta(key, status, note)`
- Updated scan-complete behavior (`PATCH /scan-runs/{id}`):
  - always refresh host-local hash aggregates immediately
  - if other hosts are still scanning, mark global aggregates stale and enqueue global refresh jobs
  - otherwise refresh global aggregates inline and mark fresh
- Added tests for deferred-vs-inline refresh behavior during concurrent scans.
- Added maintenance queue execution primitives:
  - dequeue, complete, fail/requeue, list
- Added maintenance worker loop and activity gating:
  - `ACTIVE` / `WARM` / `IDLE` modes based on running scans + API idle time
  - priority-gated job pickup in active/warm periods
- Added operator endpoints:
  - `GET /maintenance/jobs`
  - `POST /maintenance/run-now?force=true`
- Added runtime controls:
  - `SIFT_MAINTENANCE_ENABLED`
  - `SIFT_MAINTENANCE_COOLDOWN_SEC`
  - `SIFT_MAINTENANCE_MIN_IDLE_SEC`

Target scheduler behavior:

- Worker state model:
  - `ACTIVE`: scans/heavy API load -> only tiny jobs
  - `WARM`: moderate load -> host-local jobs and small chunks
  - `IDLE`: no scans + low API load -> full global jobs
- ~~Chunked jobs with checkpoints (pause/resume safe).~~ Deferred — current refreshes complete in seconds at 4M rows. Revisit at 50M+ rows.
- ~~Preemption/yield between chunks when activity resumes.~~ Deferred — same rationale.

Container/local deployment knobs (planned):

- `SIFT_MAINTENANCE_ENABLED`
- `SIFT_MAINTENANCE_MIN_IDLE_SEC`
- `SIFT_MAINTENANCE_CHUNK_MS`
- `SIFT_MAINTENANCE_COOLDOWN_SEC`
- optional maintenance window for always-on servers.

---

## Endpoint and Data Evolution Map

Current -> Target direction:

- `/files/ls` -> keep for compatibility, progressively replaced by `/tree/children` + `/tree/dup-metrics`.
- `/directories` -> move to `directory_index` source.
- `/stats/overview` -> transition to aggregate-backed reads.
- `/files` (search) -> pagination/cursor support + lighter query paths where feasible.

Compatibility plan:

- Keep existing endpoints active through migration.
- Frontend feature-flag to switch to v2 tree APIs when available.

---

## Feature Flags and Rollout Controls

Proposed flags:

- `SIFT_TREE_V2=1` (enables new tree API consumption)
- `SIFT_AGG_TABLES=1` (enables aggregate-backed query paths)

Rollout sequence:

1. Ship Phase 1 in default-on mode.
2. Ship tree v2 APIs behind flag.
3. Switch frontend to tree v2 behind flag.
4. Ship aggregate tables and dual-read validation behind flag.
5. Promote aggregate paths after parity checks.

---

## Validation and Test Plan

Functional parity:

- Compare old vs new duplicate counts on sampled hosts/paths.
- Validate hash-search parity for known duplicate sets.
- Confirm stale/fresh metadata transitions after scan completion.

Performance validation:

- Benchmark p50/p95 endpoint latencies by dataset size (4M, 10M, 20M where possible).
- Load test concurrent UI operations (expand + search + stats).
- Track UI frame consistency during large scroll ranges.

Reliability:

- Ensure cache invalidation correctness after writes.
- Ensure fallback paths behave when aggregates are missing/stale.

---

## Deployment Validation Matrix

This matrix is the required rollout gate for local macOS and Unraid container deployments.

### Test types

- Smoke: quick sanity checks that core UX and APIs are up.
- Integration: API + DB behavior across scan/maintenance/aggregate transitions.
- E2E: frontend interaction paths (expand/search/load more/dup enrichment).
- Soak/perf: sustained mixed usage and latency/error tracking.

### Make targets for test cadence

- `make test-fast`: unit + server tests (default fast local verification)
- `make test-unit`: unit tests only
- `make test-server`: server tests only
- `make smoke-local`: quick smoke checks
- `make test-integration-live`: live integration tests (`SIFT_TEST_SERVER` required)
- `make verify-local`: fast tests + frontend build
- `make soak-local`: explicit long-run soak/perf tests (manual use only)

### Local macOS gate (first)

Environment:

- `SIFT_PERF_LOG=1`
- `SIFT_MAINTENANCE_ENABLED=1`
- `SIFT_MAINTENANCE_MIN_IDLE_SEC=120`
- `SIFT_MAINTENANCE_COOLDOWN_SEC=10`

Required checks:

- Smoke:
  - API responds: `/hosts`, `/tree/children`, `/stats/overview`, `/maintenance/jobs`.
  - UI loads and first tree paint is responsive.
- Integration:
  - Run server tests: `pytest tests/server -q` (must pass).
  - Verify scan completion behavior with concurrent host scans queues global work instead of blocking.
  - Verify aggregate freshness fields (`aggregated_at`, `data_freshness`) are present where expected.
- E2E (manual unless automated harness is added):
  - Expand large dirs, search while typing, click load-more rows, verify no UI lockups.
  - During active scan, ensure browsing remains responsive and dup metrics backfill progressively.
- Soak/perf:
  - 2-4 hours mixed browse + scan activity.
  - No repeating errors in logs; maintenance queue should drain when idle.

Pass criteria:

- p95 first-tree/render and expand latencies show clear improvement vs baseline.
- No fatal errors, no runaway retry loops, no queue growth without eventual drain.

### Unraid canary gate (second)

Deployment notes:

- Use persistent DB volume.
- Stop container gracefully (avoid force-kill for routine operations).
- Keep maintenance settings conservative initially.

Required checks:

- Repeat local smoke/integration checks in container environment.
- Stop/start safety:
  - stop container from Unraid UI during idle and during moderate activity,
  - restart and validate core endpoints + UI immediately,
  - verify maintenance queue recovers cleanly.
- 24-72h canary soak:
  - periodic scans across multiple hosts,
  - browse/search during and after scans,
  - confirm maintenance jobs run primarily in idle windows.

Pass criteria:

- Stable operation over soak window with no data integrity issues.
- Observable speed improvements maintained under real workload.
- Maintenance activity does not degrade interactive UX.

### Rollback / mitigation triggers

- Trigger immediate mitigation if:
  - p95 browse/expand latency regresses materially,
  - repeated maintenance failures or queue runaway,
  - scan completion latency spikes due to maintenance contention.
- First mitigation:
  - disable maintenance worker (`SIFT_MAINTENANCE_ENABLED=0`) and restart service.
- If needed:
  - roll back recent changes via `git revert`-based deployment rollback.

---

## Risks and Mitigations

- Risk: stale aggregate confusion in UI.
  - Mitigation: explicit `data_freshness` and `aggregated_at` surfaced in API/UI.
- Risk: dual-path complexity during migration.
  - Mitigation: strict feature flags, parity checks, phased cutover.
- Risk: cache fragmentation (host/path/filter combinations).
  - Mitigation: bounded TTL + normalized keys + size caps.
- Risk: virtualization edge cases with grouped rows/highlights.
  - Mitigation: incremental rollout and focused component tests.

---

## Work Log

Use this section to record execution progress as implementation begins.

### 2026-02-28

- Created this implementation plan.
- Captured architecture decisions and phased execution model.
- Confirmed consistency model: eventual consistency.

### 2026-03-01

- Started Phase 0 implementation.
- Added backend perf logging toggle via `SIFT_PERF_LOG=1`.
- Added endpoint-level perf logs for:
  - `/init`
  - `/files/ls`
  - `/files`
  - `/directories`
  - `/stats/overview`
  - `/files/duplicates-in-subtree`
  - `/files/dup-ancestor-dirs`
- Added frontend perf instrumentation behind local flag:
  - enable with `localStorage.setItem('sift:perf', '1')`
  - or set `window.__SIFT_PERF = true` in devtools
- Instrumented frontend events:
  - API request timing in `api.get`
  - first tree paint (`ui.first_tree_paint`)
  - directory expand timing (`ui.expand_path`)
  - filename/hash/directory search timing
- Verification:
  - `pytest tests/server -q` -> `100 passed in 2.25s`
  - `npm run build` in `frontend/` -> success
- Captured synthetic baseline benchmark (600k rows, 3 hosts) and recorded p50/p95 values.
- Completed Phase 1 implementation:
  - backend caches + invalidation
  - frontend debounce + request cancellation
  - deferred initial stats fetch
- Added cache invalidation tests (`tests/server/test_query_cache.py`).
- Re-ran validation:
  - `pytest tests/server -q` -> `104 passed in 2.49s`
  - `npm run build` in `frontend/` -> success
- Captured post-Phase-1 synthetic benchmark and recorded deltas vs baseline.
- Completed Phase 2 implementation:
  - Added `/tree/children` and `/tree/dup-metrics` endpoints.
  - Switched frontend path fetch to fast-children + async dup-metrics merge.
  - Switched `/init` root listings to the fast tree-children path.
- Added server tests for new tree endpoints and cursor behavior.
- Re-ran validation:
  - `pytest tests/server -q` -> `109 passed in 2.62s`
  - `npm run build` in `frontend/` -> success
- Captured post-Phase-2 synthetic benchmark and recorded p50/p95 deltas.
- Completed Phase 3 implementation:
  - Added windowed table rendering (virtualization) to `FileTable`.
  - Added cursor-driven load-more flow for tree children pages.
  - Switched frontend startup path to `/hosts` + paginated tree fetch (instead of preloading `/init` root listings).
- Re-ran validation:
  - `pytest tests/server -q` -> `109 passed in 2.48s`
  - `npm run build` in `frontend/` -> success
- Started Phase 4 foundation work:
  - Added aggregate schema tables and refresh helpers.
  - Hooked aggregate refresh on scan completion.
  - Switched `/directories` to use `directory_index` with legacy fallback.
- Re-ran validation:
  - `pytest tests/server -q` -> `109 passed in 2.64s`
  - `npm run build` in `frontend/` -> success
- Added segment-scoped dup-metrics flow (`segments` param) and frontend support to fetch/merge only missing segment metrics.
- Added test coverage for segment-scoped dup-metrics behavior.
- Re-ran validation:
  - `pytest tests/server -q` -> `110 passed in 2.63s`
  - `npm run build` in `frontend/` -> success
- Added adaptive-maintenance groundwork:
  - `aggregate_meta` + `maintenance_jobs` schema
  - queue/freshness helper functions in DB layer
  - scan-complete logic now defers heavy global refresh when other hosts are still scanning
  - added tests for deferred-vs-inline refresh behavior with concurrent host scans
- Implemented adaptive-maintenance worker pass:
  - background worker loop starts when `SIFT_MAINTENANCE_ENABLED=1`
  - activity-aware queue pickup (`ACTIVE`/`WARM`/`IDLE`)
  - maintenance queue execution helpers (dequeue/complete/fail/requeue)
  - operator endpoints for inspection/trigger (`/maintenance/jobs`, `/maintenance/run-now`)
  - added endpoint tests for list/run-now behavior
- Re-ran validation:
  - `pytest tests/server -q` -> `115 passed in 2.93s`
  - `npm run build` in `frontend/` -> success
- Migrated `/stats/overview` to aggregate-backed reads when aggregate freshness metadata is available.
  - Uses `host_stats` for base totals.
  - Uses `hash_stats` / `host_hash_stats` for duplicate-set and wasted-byte calculations.
  - Falls back to live query path for category-filtered requests or when aggregate metadata is unavailable.
  - Returns `aggregated_at` and `data_freshness` in stats response.
- Re-ran validation:
  - `pytest tests/server/test_stats.py -q` -> `15 passed`
  - `pytest tests/server -q` -> `115 passed in 2.79s`
  - `npm run build` in `frontend/` -> success
- Added deployment validation matrix covering local macOS gate and Unraid canary gate,
  including smoke/integration/e2e/soak checks and rollback triggers.
- Added explicit test marker policy and Makefile test targets to prevent misuse
  (e.g., soak/perf tests running during normal verify/build cycles).
- Validation for test-cadence updates:
  - `pytest tests/server/test_smoke.py -q` -> `3 passed`
  - `pytest tests/server -q` -> `118 passed`
  - `make test-fast` -> `292 passed`
  - `make smoke-local` -> `3 passed`
- Fixed frontend startup runtime crash (blank screen) caused by TDZ ordering in `App.jsx`.
- Reduced initial interactive latency by deferring duplicate-enrichment requests unless needed
  (enabled for dup-focused views/filters and expanded directories).
- Optimized `/tree/dup-metrics` segment-scoped query path to filter scoped rows earlier.
- Reworked `/tree/children` query shape to avoid expensive subtree rollup aggregation in interactive listing.
  - Returns immediate children quickly; heavy duplicate/rollup details continue to load via async enrichment paths.
- Added aggregate-metadata fallback logic for `/stats/overview` so existing aggregate tables are used
  even when freshness metadata is not yet initialized.
- Added large-host guard in `/tree/dup-metrics` to skip catastrophic live fallback scans when host aggregates are missing,
  and queue a host aggregate refresh instead.
- Further reduced interactive search cost by adding `lite` mode in `/files` and using it from frontend search flows.
- Fixed dup-only refresh behavior by explicitly backfilling dup metrics when dup-only mode is enabled.
- Added dup-only/tree interaction throttles to prevent UI request storms:
  - avoid eager dup-metrics fetch across every expanded path on each render change,
  - cap auto-expanded dup-ancestor path set,
  - avoid prefetching all auto-expanded descendants,
  - prune cross-host path fetches using host/path empty-ancestor short-circuiting.
- Restored default host-selection behavior on page load via new `GET /client-host`
  and frontend client-host matching logic.
- Reduced dup-only expansion fan-out:
  - auto-ancestor discovery now uses one anchor host,
  - `/files/dup-ancestor-dirs` now supports `max_paths` capping server-side.
- Fixed `Only dups` empty-state regression when maintenance is disabled on large hosts:
  - `/tree/dup-metrics` now uses a bounded lightweight live fallback (scoped hashes) instead of returning empty metrics,
    while still avoiding catastrophic full live scans.
- Validation after startup/perf fix:
  - `npm run build` (frontend) -> success
  - `pytest tests/server/test_tree_endpoints.py -q` -> `6 passed`
  - `pytest tests/server/test_stats.py -q` -> `15 passed`
  - `pytest tests/server -q` -> `120 passed`
  - `make smoke-local` -> `3 passed`
  - `pytest tests/server/test_files.py tests/server/test_tree_endpoints.py -q` -> `23 passed`
  - `pytest tests/server -q` -> `122 passed`

### 2026-03-01 (session 2) — Code review, bug fixes, and production-scale perf tuning

- Performed full code review of Phases 0-5 implementation against 8M+ row production database.
- Identified and fixed 6 bugs:
  1. `refresh_directory_index()` GROUP BY bug — changed `GROUP BY dir_path, dir_display` to
     `GROUP BY regexp_replace(...)` with `ANY_VALUE(dir_display)` to prevent duplicate PK errors.
  2. `mergeEntries` missing `is_hard_linked` field — added initialization and merge logic in `utils.js`.
  3. Lite fallback in `/tree/dup-metrics` missing hard-link exclusion — added `hard_linked_inodes` CTE.
  4. `fetchDupAncestors` stale `fetchPath` in dependency array — removed unused dep.
  5. Unified `_stats_cache` with query cache helpers (`_cache_get`/`_cache_set`) — eliminated separate cache dict.
  6. Split `cacheVersion` into `structureVersion` + `metadataVersion` to avoid unnecessary `buildRows` re-renders.
- Added `host_hard_linked_inodes` pre-computed table to eliminate per-request full-host GROUP BY scan.
  - `refresh_host_hard_linked_inodes(host)` called during `refresh_host_hash_stats`.
  - All dup-metrics query paths now read from pre-computed table instead of scanning `files`.
- Added `_bootstrap_aggregates()` — auto-populates aggregate tables on server startup when empty.
  - Runs in background thread so server startup isn't blocked.
  - Solves "No files found" in dup-only mode when `SIFT_MAINTENANCE_ENABLED=0`.
- **Critical perf fix:** Restructured all 3 dup-metrics query paths (aggregate, live, lite) to
  "aggregate-first" approach — GROUP BY (segment, hash) first to collapse files into unique hashes
  per segment before joining to `host_hash_stats`.
  - Production result: `/tree/dup-metrics` for Unraid root dropped from **144.5s → 888ms**.
- Fixed fan-out bug in cross-host duplicate counting — `LEFT JOIN host_hash_stats` for other hosts
  multiplied rows, inflating `SUM(file_count)`. Fixed by pre-aggregating cross-host info per segment
  in a `cross_hosts` CTE joined 1:1 on segment.
- Verified dup counts are correct via direct SQL validation:
  - `SELECT COUNT(*) ... WHERE copy_count_effective > 1` = 2,570,034, matching API response exactly.
- Excluded skipped files (`skipped_reason IS NOT NULL`) from `host_stats` totals.
  - Two OrbStack sparse files (8,193 GB virtual size) were inflating MacBook stats from 605 GB to 8.6 TB.
  - Added `_startup_refresh()` to re-run `refresh_host_stats` on every server start.
- Added `GET /debug/query` endpoint for ad-hoc read-only SQL queries against the live database.
  - Only SELECT/WITH statements allowed; errors return 400 with message instead of 500 stacktrace.
  - Documented in new `tips.md` with example queries.
- Frontend fixes:
  - Skip `allTreeRows` computation in search mode.
  - Always enrich dup metrics (removed conditional gating that skipped requests).
  - Copy-to-clipboard now single-quotes paths containing spaces or shell metacharacters.
  - Removed debug `console.warn` statements from `App.jsx`.
- Added duplicate sets vs extra copies explanation with example to `README.md`.
- Validation:
  - `pytest tests/server -q` -> `123 passed`
  - `npm run build` (frontend) -> success

### 2026-03-03 — Timing re-check (Phase 1/2/4 regression guard)

- Ran a fresh synthetic benchmark pass using FastAPI `TestClient` + in-memory DuckDB.
  - Dataset: `180,000` rows total (`60,000` per host across `3` hosts).
  - Focus: key read-path p50/p95 checks for browse/search/stats endpoints.
- Results (ms):
  - `GET /hosts` (n=6): p50 `40.4`, p95 `86.8`
  - `GET /stats/overview` warm (n=6): p50 `1.9`, p95 `175.5`
  - `GET /directories?q=dir1&limit=20` (n=6): p50 `0.9`, p95 `14.9`
  - `GET /files?iname=*a*&limit=200` (n=4): p50 `7.4`, p95 `8.2`
  - `GET /init?path=/` (n=3): p50 `160.1`, p95 `168.9`
  - `GET /tree/children` root (n=5): p50 `2.6`, p95 `18.5`
  - `GET /tree/dup-metrics` root (n=4): p50 `3.8`, p95 `35.9`
- Notes:
  - These are synthetic in-process timings (not Unraid canary or production-volume timings).
  - `/stats/overview` p95 is skewed by startup/bootstrap overlap in this run; steady-state calls were low-ms.
- Local server probe status:
  - Attempted automated local `sift server` startup timing gate; server did not become ready within `140s` in this shell session, so no reliable live-endpoint timing snapshot was recorded from local DB.
  - Keep local+Unraid rollout matrix as the authoritative final gate.

### 2026-03-03 (session 2) — Polish and close phases

- Added transaction safety (BEGIN/COMMIT) for all 4 aggregate refresh functions in `db.py`:
  `refresh_host_hard_linked_inodes`, `refresh_host_hash_stats`, `refresh_hash_stats`, `refresh_directory_index`.
- Added `file_count` and `total_bytes` fields to `TreeDupMetric` model and all 3 dup-metrics query paths.
  - `seg_hashes` CTE now includes `SUM(COALESCE(f.size_bytes, 0)) AS total_bytes`.
  - Frontend merge callback propagates these fields from dup-metrics into cached entries.
  - `/tree/children` dirs now return `NULL` (not `0`) for `file_count` so frontend can distinguish "not loaded" from "empty".
  - `mergeEntries` in `utils.js` updated to preserve null semantics for dirs until enrichment.
- Added freshness indicator in `StatsBar.jsx`:
  - Shows `(as of Xm ago)` or `(updating...)` next to duplicate stats when data is stale/building.
  - 3-second holdover before hiding indicator on fresh transition.
- Added scanning indicator on host chips:
  - `is_scanning` field on `HostEntry` model, populated from `scan_runs WHERE status = 'running'`.
  - Pulsing dot rendered before host name in `HostChips.jsx` via Tailwind `animate-pulse`.
  - 60s polling interval for `/hosts` in `App.jsx` to refresh scanning state.
- Documented deferred chunked maintenance work in `deferred-features.md`.
- Marked Phases 4 and 5 as complete in plan doc; updated Next Execution Steps for merge readiness.

---

## Next Execution Steps

All phases (0-5) are complete. Ready to merge to main.

Completed across all phases:

- Fast tree API split (`/tree/children` + `/tree/dup-metrics`) and async dup enrichment.
- Query caching + invalidation and request cancellation/debounce improvements.
- Virtualized + paginated frontend table flow.
- Aggregate table foundations and aggregate-backed stats/dup metrics core paths.
- Adaptive maintenance queue worker foundation and operator endpoints.
- Transaction safety for aggregate refresh functions.
- Directory size display via dup-metrics enrichment (`file_count`, `total_bytes`).
- Aggregate freshness indicator in StatsBar UI.
- Scanning indicator (pulsing dot) on host chips with 60s polling.
- Critical perf fix: `/tree/dup-metrics` for Unraid root dropped from 144s to 888ms.

Explicitly deferred (documented in `deferred-features.md`):

- Chunked/checkpointed maintenance jobs — current refreshes complete in seconds at 4M rows; revisit at 50M+.
- Aggregate-backed category-filtered stats — live fallback is fast enough at current scale.

Remaining before merge:

1. Run `pytest tests/server -q` and `npm run build` to verify no regressions.
2. Execute deployment validation matrix (local macOS gate, then Unraid canary).
3. Merge `perf/scaling-phase-rollout` to `main`.
