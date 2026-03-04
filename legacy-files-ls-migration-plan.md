# Legacy `/files/ls` Migration and Deprecation Plan

## Purpose

Migrate runtime callers away from legacy `GET /files/ls` to avoid rare catastrophic long-running queries and lock contention, while preserving frontend behavior and protecting `GET /files/ls/dup-hash`.

This plan is designed for multiple coding agents to execute incrementally and track progress safely.

## Prime Directive

Any change must satisfy both:

1. Do not break frontend behavior.
2. Do not degrade database performance.

If either cannot be demonstrated by tests + benchmarks, stop rollout and keep compatibility behavior.

## Verified Current State (from code audit)

- Runtime callers of `GET /files/ls`:
  - `sift ls` in `sift/commands/ls.py`.
  - `sift du` in `sift/commands/du.py`.
- Frontend does not currently call `GET /files/ls`.
- Frontend does call `GET /files/ls/dup-hash` (`1 extra copy` flow), which must remain supported.
- Maintenance worker paths do not call `GET /files/ls`; they run DB refresh jobs directly.
- `sift find` does not call `/files/ls`, but can still be a DB offender via `/files` in high-limit/duplicate modes.

## Scope

### In scope

- Migrate CLI runtime usage from `/files/ls` to `/tree/children` + `/tree/dup-metrics`.
- Keep `/files/ls/dup-hash` working during and after `/files/ls` deprecation.
- Evaluate and harden `sift find` to avoid poor DB access patterns.
- Deprecate and later remove `/files/ls` endpoint and tests that depend on it.

### Out of scope (for now)

- Full redesign of all duplicate/stat endpoints.
- Non-essential response shape changes for existing frontend endpoints.

## Progress Tracker

Use checkboxes and update as work lands.

### Phase 0 - Baseline and Guardrails

- [ ] Capture baseline perf and lock behavior for:
  - [ ] `sift ls` on large paths
  - [ ] `sift du` on large paths
  - [ ] `sift find` normal and `-duplicates`
  - [ ] frontend tree browse + dup-hash click flow
- [ ] Record baseline p50/p95 and max latency for key endpoints.
- [ ] Enable/request-log sampling during migration to verify live endpoint usage.
- [ ] Define hard fail gates (examples):
  - [ ] No frontend functional regressions
  - [ ] No new long lock fan-out events
  - [ ] No endpoint p95 regression beyond agreed threshold

### Phase 1 - Migrate CLI Off `/files/ls`

- [x] Update `sift ls` to use `/tree/children` + `/tree/dup-metrics`.
- [ ] Preserve current CLI semantics:
  - [ ] sorting
  - [ ] duplicate filtering
  - [ ] recursive/file lookup behavior
  - [ ] host/all-hosts behavior
- [x] Update `sift du` to use `/tree/children` + `/tree/dup-metrics`.
- [ ] Preserve current `du` semantics:
  - [ ] summarize/depth behavior
  - [ ] duplicates-only behavior
  - [ ] host/all-hosts behavior

### Phase 2 - `sift find` DB-Access Hardening

- [ ] Benchmark `sift find` as currently implemented on large datasets.
- [ ] Identify worst offender cases (expected: `-duplicates`, high limits, all-hosts).
- [ ] Implement safe improvements (as needed), such as:
  - [ ] selective `lite` path usage when cross-host enrichment is unnecessary
  - [x] duplicate filter optimization in `/files`
  - [ ] bounded limits and/or pagination strategy
- [ ] Re-benchmark and confirm no regression.

### Phase 3 - Protect `/files/ls/dup-hash`

- [ ] Keep `/files/ls/dup-hash` route fully supported while deprecating `/files/ls`.
- [ ] Add/keep explicit contract tests for dup-hash invariants:
  - [ ] returned hash resolves to `>= 2` files via `/files?hash=...`
  - [ ] 404 when no qualifying duplicate hash exists in subtree
- [x] Ensure dup-hash tests do not rely on `/files/ls` for candidate discovery.

### Phase 4 - Deprecate Runtime `/files/ls`

- [ ] Add deprecation warning log for `/files/ls` calls.
- [ ] Verify zero runtime callers remain (CLI + frontend).
- [ ] Keep a short compatibility window.
- [ ] Remove `/files/ls` endpoint after stability window.

### Phase 5 - Deprecate Legacy `/files/ls` Tests

- [ ] Mark and remove/replace tests that directly target `/files/ls` behavior.
- [ ] Replace with tree-endpoint and invariant-based tests.
- [ ] Candidate files to update:
  - [ ] `tests/server/test_ls.py`
  - [ ] `tests/server/test_query_cache.py` (`/files/ls` cache expectations)
  - [ ] `tests/server/test_ingest.py` (`/files/ls` assertions)
  - [x] `/files/ls` portions of `tests/integration/test_live.py`

### Phase 6 - Final Validation and Rollout

- [ ] Run full test suite and targeted integration/live checks.
- [ ] Run mixed-load soak (frontend + CLI concurrency).
- [ ] Confirm no long lock fan-out pattern in logs.
- [ ] Confirm `/files/ls/dup-hash` UI flow remains healthy.
- [ ] Document migration completion and endpoint deprecation status.

## Acceptance Criteria

All must pass before removing `/files/ls`:

- [ ] Frontend behavior unchanged for tree browse, stats, duplicate interactions.
- [ ] `1 extra copy` flow works end-to-end through `/files/ls/dup-hash`.
- [ ] CLI (`ls`, `du`, `find`) behavior matches expected output semantics.
- [ ] Database performance is stable or improved versus baseline.
- [ ] No recurring long lock contention events attributable to legacy path.

## Rollback Conditions

Rollback/hold deprecation if any occur:

- Frontend regression in tree or duplicate workflows.
- `dup-hash` contract failures.
- Significant p95 latency regressions or renewed lock storms.
- CLI behavior mismatch that breaks expected scripting usage.

## Notes for Agents

- Prefer additive and flaggable changes where possible.
- Keep response contracts stable unless tests and callers are updated in the same change.
- Land migration in small PRs with measurable perf evidence.
- Update this document's checkboxes in each PR.

## Execution Log

Use this log to track implementation history across agents and sessions.
Add new entries at the top (newest first).

### Entry Template

```md
### YYYY-MM-DD - Agent/Author - Short Title

- Scope:
  - <what this change set intended to do>
- Files changed:
  - `<path>`
  - `<path>`
- Checklist updates:
  - [x] <checkbox or phase item completed>
  - [ ] <remaining item if partial>
- Validation run:
  - `<command>` -> <pass/fail + key signal>
  - `<command>` -> <pass/fail + key signal>
- Perf notes:
  - Baseline: <metric(s)>
  - After: <metric(s)>
  - Result: <improved/same/regressed>
- Frontend safety notes:
  - <what was checked to ensure no frontend breakage>
- Risks / follow-ups:
  - <known risk>
  - <next step>
```

### Entries

### 2026-03-04 - OpenCode - Find Hardening and Legacy-Test Migration (Partial)

- Scope:
  - Hardened duplicate filtering in `GET /files` to prefer aggregate-backed paths (`host_hash_stats` / `hash_stats`) before raw-table fallback.
  - Migrated live integration coverage away from `/files/ls` to tree v2 helper (`/tree/children` + `/tree/dup-metrics`).
  - Added unit tests asserting CLI `ls` and `du` use tree endpoints and not legacy `/files/ls`.
- Files changed:
  - `server/main.py`
  - `tests/integration/test_live.py`
  - `tests/unit/test_commands_ls_du_tree_api.py`
  - `legacy-files-ls-migration-plan.md`
- Checklist updates:
  - [x] duplicate filter optimization in `/files`
  - [x] Ensure dup-hash tests do not rely on `/files/ls` for candidate discovery
  - [x] `/files/ls` portions of `tests/integration/test_live.py`
  - [ ] `sift find` large-dataset benchmarking
  - [ ] bounded limits/pagination strategy for `sift find`
- Validation run:
  - `pytest tests/unit/test_commands_ls_du_tree_api.py -q` -> `2 passed`
  - `pytest tests/server/test_files.py tests/server/test_tree_endpoints.py -q` -> `25 passed`
  - `make test-fast` -> `308 passed`
- Perf notes:
  - Baseline: long `/files/ls` lock contention previously observed in production logs.
  - After: aggregate-backed `/files` duplicate filter now preferred where aggregates exist; live perf measurement still pending.
  - Result: expected improvement for `sift find -duplicates` path on aggregate-ready hosts.
- Frontend safety notes:
  - Frontend endpoint contracts unchanged.
  - `/files/ls/dup-hash` kept intact; integration tests still validate this flow.
- Risks / follow-ups:
  - Need live benchmark run to quantify `sift find` changes.
  - Remaining legacy `/files/ls` server tests should be replaced in a later phase.

### 2026-03-04 - OpenCode - CLI Migration for `ls` and `du`

- Scope:
  - Migrated runtime CLI listing paths from legacy `/files/ls` to tree v2 endpoints.
  - Implemented merged fetch flow: paged `/tree/children` + chunked `/tree/dup-metrics`.
  - Preserved entry-shape expectations used by existing CLI output code.
- Files changed:
  - `sift/commands/ls.py`
  - `sift/commands/du.py`
  - `legacy-files-ls-migration-plan.md`
- Checklist updates:
  - [x] Update `sift ls` to use `/tree/children` + `/tree/dup-metrics`
  - [x] Update `sift du` to use `/tree/children` + `/tree/dup-metrics`
  - [ ] CLI semantic parity verification (manual/live)
  - [ ] Phase 0 baseline perf capture
- Validation run:
  - `pytest tests/unit -q` -> `178 passed`
  - `make test-fast` -> `306 passed`
- Perf notes:
  - Baseline: pre-change production lock evidence already observed in server logs (long `/files/ls`).
  - After: no live benchmark captured yet in this session.
  - Result: expected improvement by removing CLI runtime dependency on `/files/ls`; pending live confirmation.
- Frontend safety notes:
  - Frontend codepaths untouched in this change set.
  - `/files/ls/dup-hash` untouched and still available for `1 extra copy` flow.
- Risks / follow-ups:
  - Need live parity checks for `du` depth/summarize and `ls` recursive/file lookup on real data.
  - Need Phase 0 quantitative perf capture to close prime-directive evidence gap.

### 2026-03-04 - OpenCode - Planning Baseline and Migration Checklist

- Scope:
  - Created and finalized the migration/deprecation plan for legacy `/files/ls`.
  - Confirmed runtime callers and added explicit protection requirements for `/files/ls/dup-hash`.
  - Added phased checklist including `sift find` DB-access review and legacy test deprecation.
- Files changed:
  - `legacy-files-ls-migration-plan.md`
- Checklist updates:
  - [x] Draft complete multi-phase migration/deprecation plan
  - [x] Include `/files/ls/dup-hash` protection requirements
  - [x] Include maintenance-worker non-usage verification requirement
  - [x] Include `sift find` offender analysis phase
  - [x] Include legacy `/files/ls` test deprecation phase
  - [ ] Phase 0 baseline perf capture
  - [ ] Phase 1 CLI migration (`sift ls`, `sift du`)
- Validation run:
  - `code audit (server + CLI + frontend call paths)` -> completed; runtime `/files/ls` callers identified as `sift ls` and `sift du`
  - `maintenance path inspection` -> completed; no maintenance worker calls to `/files/ls`
- Perf notes:
  - Baseline: not yet captured in this plan execution log.
  - After: N/A (planning-only change).
  - Result: N/A.
- Frontend safety notes:
  - Verified frontend does not call `/files/ls` in active app flow.
  - Verified frontend uses `/files/ls/dup-hash` for the `1 extra copy` interaction; route retained in plan.
- Risks / follow-ups:
  - Must capture quantitative baseline before code migration begins.
  - Must preserve CLI output semantics during endpoint migration.
