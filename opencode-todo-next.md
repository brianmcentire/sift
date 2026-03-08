# OpenCode TODO Next

Post-session review notes after deep pass on changed files (`frontend/src/App.jsx`, `frontend/src/api.js`, `server/main.py`, `server/models.py`, CLI/test/docs updates).

## High-priority follow-ups

1. Clarify and lock `/tree/dup-metrics` contract with `host` vs `hosts`
   - Current endpoint accepts both `host` and `hosts` and silently prefers `hosts` when non-empty.
   - Add explicit validation/rules (for example: reject both set simultaneously, or document precedence explicitly).
   - Add tests for mixed-parameter behavior.

2. Deduplicate duplicate SQL between `/files/duplicates-by-subtree-hashes` and `/files/duplicates-by-subtree-hashes/count`
   - Both endpoints implement near-identical seed-hash logic (freshness gate, selected-host scope, min size/category/drive/path constraints).
   - Refactor shared query-builder/helper to prevent drift regressions.
   - Add parity test: count endpoint equals `COUNT(DISTINCT hash)` from list endpoint for same params.

3. Add regression tests for Windows-drive subtree highlight behavior
   - The recent `toResultPathKey` fix addressed `drive:path_display` normalization mismatch.
   - Add explicit tests for `C:` + subtree/context overlays to ensure `in_subtree` highlighting remains stable.

4. Add regression tests for selected-host scope cache invalidation in tree dup metrics
   - Frontend now keys metric state by `selectedScopeKey`; this fixed stale counts when host selection changed.
   - Add coverage for host-toggle sequence to prevent reintroduction (same path + min size, different selected host set).

## Performance follow-ups

5. Revisit drive-level count API call frequency
   - `driveDupHashCounts` currently makes one count request per available drive when in Tree View.
   - Add lightweight memoization/throttle keyed by `(selectedHosts, minDupSize, categories, drive)` or refresh only on meaningful changes.
   - Validate no negative impact on API pending churn for large host sets.

6. Consider folding drive uniq-hash counts into host-set `/tree/dup-metrics` response
   - The dedicated count endpoint fixed correctness quickly but increases API surface and duplicate query paths.
   - Evaluate replacing count endpoint with exact root-segment metrics from host-set `/tree/dup-metrics` to reduce maintenance.
   - Keep only if parity/perf is equivalent.

## Maintainability follow-ups

7. Break `frontend/src/App.jsx` into focused hooks/modules
   - `App.jsx` now contains intertwined concerns: tree cache, list mode paging, overlays, back stacks, request-state indicator, dup semantics.
   - Suggested extraction:
     - `useTreeData(...)`
     - `useListViewData(...)`
     - `useOverlayNavigation(...)`
     - `useApiPendingIndicator(...)`
   - This will reduce regression risk and make future semantic updates easier.

8. Normalize terminology cleanup pass
   - Docs are mostly updated, but code comments/labels still contain some legacy copy semantics references.
   - Ensure consistent terms everywhere:
     - directory rows: `uniq dup hashes`
     - file rows: `extra copies`
     - action semantics: scoped (`text`) vs context (`list icon`).

9. Add one explicit architecture note for duplicate semantics
   - Add a short design note linking:
      - `duplicate-semantics.md`
     - `/files/duplicates-by-subtree-hashes` semantics
     - `/tree/dup-metrics` selected-host behavior
   - Goal: single place future agents can trust for intended behavior.

## Nice-to-have diagnostics

10. Add optional dev-only diagnostic overlay for duplicate metric state
   - Show: selected host scope key, tree metrics refresh state, and last dup endpoint params.
   - Keep behind a debug flag/environment gate only.
   - Useful for quickly diagnosing future "row count vs click result" mismatches.
