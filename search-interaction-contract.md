# Search Interaction Contract

This document defines the intended search/filter interaction model across Tree View, List View, and overlay result states.

Code is authoritative for current behavior and contracts, except where behavior is clearly a bug.

## Scope and Canonical References

- Product-level behavior: `README.md`
- Duplicate semantics and click-through meaning: `duplicate-semantics.md`
- Live API and query contract: `server/main.py`

## Prime Directive (Search + Filtering)

- Prefer bounded, incremental queries over global/heavy operations.
- Reuse existing endpoints and semantics before adding new query paths.
- Do not change search/filter behavior in ways that break duplicate click-through reliability.
- If a change risks major perf/safety regressions, pause and ask before proceeding.

## Modes

- `Tree View`: navigation-first mode.
- `List View`: flat, paged inventory mode across selected hosts.
- `Overlay`: result-first mode entered from tree/search duplicate flows (e.g., filename/hash results, duplicate click-through).

## Input Semantics by Mode

- Directory input (`dirQuery`):
  - Tree View: finds directories to open/expand (navigation aid), not a global file-row filter.
  - List View: maps to `path_contains` and filters paged rows by path match.
  - Overlay: applies only where explicitly supported by overlay rules below.
- Filename input (`filenameQuery`):
  - Tree View: drives filename-result overlay behavior.
  - List View: filters paged rows server-side.
  - Overlay: can refine current overlay rows where overlay supports client-side refinement.
- Hash input (`hashQuery`):
  - Tree View: drives hash-result overlay behavior.
  - List View: filters paged rows server-side.
  - Overlay: can refine current overlay rows where overlay supports client-side refinement.

## Result Precedence

- Active overlay/search result set takes precedence over plain tree rows.
- With no active overlay/search result set:
  - List View renders list rows.
  - Tree View renders tree rows (including directory-search navigation behavior).

## Cross-View Contract

- Tree and List semantics are intentionally different where needed:
  - Tree emphasizes discovery/navigation and duplicate workflows.
  - List emphasizes composable filtering and paging.
- Mode switches preserve user intent but must not leak tree-side effects into list queries.
- Tree-only effects are guarded so List View filtering does not trigger tree expansion/search side effects.

## Overlay Contract

- Duplicate overlays (`extra copies`, `uniq dup hashes` click-through flows) preserve duplicate semantics and host-scope correctness.
- Generic list-style filtering must not silently remove expected click-through rows in duplicate overlays.
- Overlay state should support return/back behavior without losing core context.
- `in_subtree` highlighting semantics are preserved for context overlays per `duplicate-semantics.md`.

## Filter Composition Rules

- Hosts/category/size/duplicate toggles are composable with the active mode semantics.
- Size floor (`Min size`) applies universally to all files in both Tree View and List View; files below the threshold are hidden regardless of duplicate status.
- Hash search results bypass size and category filters entirely; hash-result overlays always show all matches.
- Duplicate-only filtering respects selected-host duplicate scope semantics.

## UX Signaling Rules

- Placeholder text communicates mode-specific meaning:
  - Directory input: Tree `folder to open...`, List `path contains...`
  - Filename input: `filename contains...`
  - Hash input: `hash prefix or full...`
- A visible control that does not apply in a state must be clearly signaled as paused/disabled, or explicitly documented as intentionally active in that state.

## Invariants

- No visible, active-looking control may appear to apply while having no effect without clear UI signaling (this includes "Load more" controls during pending dup-discovery scans).
- Tree navigation behavior remains predictable when directory search is active.
- List pagination/sorting correctness is preserved under active filters.
- Duplicate click-through flows remain reliable and semantically correct.
- Mode transitions do not corrupt filter state or create hidden cross-mode side effects.

## Reset Contract

- Reset returns the UI to fresh-load behavior:
  - Clears all search queries (directory, filename, hash).
  - Clears `Only dups`, `Min size`, and category filters.
  - Clears all overlays, pinned results, and overlay back stacks.
  - Collapses all expanded directories (resets expansion state).
  - Switches to Tree View.
  - Reselects the browser-matching host if present among available hosts; otherwise selects all hosts.
- Reset must not leave stale filter state, cached overlay rows, or orphaned UI indicators.

## Overlay Highlight Rules

- File rows in overlay result sets use yellow highlighting (`bg-amber-50`) for displayed duplicates by default.
- Blue highlighting (`bg-blue-50`) is reserved for rows that are inside or beneath the originating subtree path in a context overlay.
- Where both yellow and blue could apply (a row is both a duplicate and inside the originating subtree), blue takes precedence.
- These color semantics are shared with `duplicate-semantics.md` § Overlay Color Semantics.

## List-Mode Category Filter Rule

- The category picker in List View remains multi-selectable.
- Available category choices must be derived from the unfiltered data source, not from currently visible filtered results.
- This prevents the picker from collapsing to only the currently active selection, which would block the user from adding categories back.

## Load More Pending State

- If a tree branch is still scanning for dup-relevant rows (e.g., paging through children to find dup-eligible descendants under `Only dups`), any "Load more" control for that branch must signal pending/disabled state.
- A "Load more" button must not appear active and clickable while the frontend is still awaiting results that determine whether additional rows exist.

## Tagged Follow-ups

- [TBD] Finalize one explicit rule for directory input during all overlay states:
  - `clear`, `paused/disabled`, or `composable`.
  - Current implementation may vary by overlay subtype; this must be unified and documented as a single rule.
- [TBD] Finalize overlay group sorting contract for duplicate result overlays:
  - Keep rows grouped by duplicate hash; sorting reorders groups, not members across groups.
  - Group representative by sort key:
    - `size`: group size metric
    - `date`: oldest for ascending, newest for descending
    - `name`: first alpha for ascending, last alpha for descending
    - `seen`: oldest/newest by direction
    - `type`: category alpha
    - `hash`: hash alpha
  - Default overlay ordering: `name asc` with deterministic secondary tie-break (for stable renders).
  - [FUTURE] Secondary sort selection (for example, shift-click) may be added later; if added, preserve clear primary/secondary precedence.
- [DONE] Lightweight regression checklist: `frontend-regression-checklist.md`.
- [FUTURE] Revisit whether Tree and List should converge on a single composable search model.
- [FUTURE] Revisit dedicated path column support in List View if usability requires it.
- [FUTURE] Revisit persistence of List View state across sessions if needed.
