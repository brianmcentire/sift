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
- List View size floor behaves as universal minimum file size (UI label: `Min file size`).
- Tree View size floor remains duplicate-oriented for duplicate workflows (UI label: `Min dup size`).
- Duplicate-only filtering respects selected-host duplicate scope semantics.

## UX Signaling Rules

- Placeholder text communicates mode-specific meaning:
  - Directory input: Tree `folder to open...`, List `path contains...`
  - Filename input: `filename contains...`
  - Hash input: `hash prefix or full...`
- A visible control that does not apply in a state must be clearly signaled as paused/disabled, or explicitly documented as intentionally active in that state.

## Invariants

- No visible, active-looking filter may appear to apply while having no effect without clear UI signaling.
- Tree navigation behavior remains predictable when directory search is active.
- List pagination/sorting correctness is preserved under active filters.
- Duplicate click-through flows remain reliable and semantically correct.
- Mode transitions do not corrupt filter state or create hidden cross-mode side effects.

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
- [TODO] Add/keep a lightweight regression checklist for:
  - Tree search + overlay transitions,
  - List filter + pagination resets,
  - Duplicate overlay click-through integrity.
- [FUTURE] Revisit whether Tree and List should converge on a single composable search model.
- [FUTURE] Revisit dedicated path column support in List View if usability requires it.
- [FUTURE] Revisit persistence of List View state across sessions if needed.
