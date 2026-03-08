# File List View: Spec and Implementation Plan

## Goal

Add a new **List View** to the frontend that shows a flat, pageable file list across the **entire selected-host inventory**.

- Default remains **Tree View** on page load.
- User can toggle between **Tree View** and **List View** from the top-left control.
- List View reuses existing filters and sorting controls.
- List View must be performant on large datasets via server-side paging.
- Existing behavior outside List View should remain unchanged.

---

## Naming and UX

Use explicit names:

- `Tree View`
- `List View`

Replace prior internal wording "flat mode" with "list view" in code/comments/docs.

Top-left indicator behavior:

- Current Tree View label/action: switch to List View.
- Current List View label/action: switch to Tree View.

No redesign of the current UI is required; this is a mode switch layered onto existing layout and table components.

---

## Functional Requirements

## Aligned decisions (locked)

1. Keep current hash matching semantics:
   - full 64-char hash query: exact match.
   - shorter hash query: contains match.
2. Implement List View data loading through new paged endpoint (`GET /files/page`).
3. Keep existing `/files` endpoint behavior unchanged for compatibility.
4. Use debounced List View search requests and abort stale in-flight requests.
5. Preserve existing Tree View and duplicate-overlay workflows.
6. In List View, size filter behaves as **min file size** (universal floor), with label text updated by mode.
7. For `/files/page` duplicate filtering, use strict aggregate readiness gating: if selected-host duplicate aggregates are not fresh, return HTTP `202` pending (no heavy fallback query).
8. List View v1 accepts no dedicated path column as an intentional tradeoff.

## View behavior

1. Initial load opens in **Tree View** (existing behavior).
2. Switching to **List View** shows files from all selected hosts, not scoped to `currentPath`.
3. Switching back to Tree View restores existing tree behavior/state.

## Filter behavior in List View

List View should respect these existing controls/state:

- Host selection (`selectedHosts`) — required.
- Category filter (`categoryFilter`) — multi-select.
- Dup-only toggle (`onlyDups`) — duplicates within selected hosts only.
- Size floor (`minDupSize` state reused) — applied as universal minimum file size in List View.
- Search boxes act as native List View filters in real time while typing.

Clarifications:

- List View base dataset is global over selected hosts (no tree path constraint).
- `minDupSize` in List View always maps to `min_size` (universal file-size floor).
- If `onlyDups=true`, duplicate determination is within selected hosts only, then `min_size` is applied as an additional floor.

Mode-specific label text for the size control:

- Tree View: `Min dup size`
- List View: `Min file size`

Performance note:

- Universal `min_size` in List View is expected to improve or preserve performance by reducing row counts early.
- If production validation shows regressions in specific query plans, revisit and adjust.

## Search behavior in List View

In List View, search inputs filter the active list directly (server-backed) and are not treated as tree navigation controls.

- Filename search (`filenameQuery`) maps to `iname` on `/files/page`.
- Directory search (`dirQuery`) maps to `path_contains` on `/files/page` and matches anywhere in path.
- Hash search (`hashQuery`) maps to `hash` on `/files/page`.

Real-time behavior requirements:

- Debounced fetch on input changes.
- Cancel in-flight request when a newer search request starts.
- Reset pagination to first page on any search change.
- Keep server-side sorting active while filtering.

## Cross-view search semantics (explicit)

To avoid regressions and preserve existing successful flows, search semantics are intentionally mode-specific:

- **Tree View**
  - Directory search remains tree-navigation behavior (`/directories` + expand/collapse path chains).
  - Existing tree/overlay behavior is preserved.

- **List View**
  - Directory search is a list filter via `path_contains` (match anywhere in path).
  - Filename and hash boxes are native list filters with paged server queries.

- **Duplicate click overlays** (`extra copies`, `uniq dup hashes`)
  - Keep scoped overlay semantics intact.
  - Do not force generic List View filtering semantics onto these overlays.
  - Preserve current guardrails that prevent valid duplicate click-through rows from being hidden.

UX note:

- Use helper text inside search inputs (placeholders), not tooltips.
- Recommended placeholder copy:
  - Directory box:
    - Tree View: `find folder to open…`
    - List View: `path contains…`
  - Filename box (both modes): `filename contains…`
  - Hash box (both modes): `hash prefix or full…`

## Sorting behavior

List View supports sortable columns using existing table headers:

- Name (filename)
- Size
- Modified
- Last Seen
- Type
- Hash

Sorting must be server-side in List View (for correctness with pagination).

Default List View sort:

- `name asc`

---

## API Design: New Endpoint

Add a new endpoint to avoid changing existing `/files` behavior:

- `GET /files/page`

## Query params

- `hosts: string` (comma-separated host names)
- `categories: string` (comma-separated categories; optional)
- `has_duplicates: bool` (optional)
- `min_size: int` (optional)
- `max_size: int` (optional)
- `path_contains: string` (optional; used by List View directory box)
- `iname: string` (optional)
- `hash: string` (optional)
- `sort_by: string` (`name|size|date|seen|type|hash|path`)
- `sort_dir: string` (`asc|desc`)
- `limit: int` (default e.g. 200, bounded)
- `cursor: string` (offset cursor, same convention as `/tree/children`)

## Response shape

```json
{
  "items": [
    {
      "host": "mac",
      "drive": "",
      "path_display": "/users/brian/a.txt",
      "filename": "a.txt",
      "ext": "txt",
      "file_category": "document",
      "size_bytes": 1000,
      "hash": "...",
      "mtime": 1730000000,
      "last_seen_at": "2026-03-05T12:00:00Z",
      "other_hosts": "nas"
    }
  ],
  "next_cursor": "200",
  "has_more": true
}
```

`items` row schema should remain aligned with existing `FileEntry` so frontend conversion (`fileEntryToRow`) stays reusable.

---

## Duplicate Semantics (List View)

When `has_duplicates=true`, duplicates are evaluated within the selected host set only.

Definition:

- A file is duplicate if its hash appears more than once in the selected host pool,
  accounting for effective same-host copies (`copy_count_effective`) where possible.

Preferred execution path:

1. Use `host_hash_stats` aggregate table when available.
2. Build selected-host duplicate hash set by grouping selected host rows by hash and requiring combined effective copies > 1.
3. Join/filter `files` rows against that set.

Strict readiness behavior (no heavy fallback):

- For `has_duplicates=true`, check aggregate freshness for each selected host using `aggregate_meta` key `host_hash_stats:{host}`.
- If any selected host is missing freshness metadata or not `fresh`, return HTTP `202` with:

```json
{
  "status": "pending",
  "detail": "Duplicate index is still building"
}
```

- Do not run inline `GROUP BY` fallback on `files` for this endpoint.

This matches requested behavior: **duplicates within selected hosts only**, not global.

Hash filter behavior for `/files/page` should match current `/files` behavior:

- `len(hash) == 64` → exact match.
- otherwise → contains match.

---

## Performance Requirements

1. No full inventory fetch in one request.
2. Page-by-page loading via `limit + cursor`.
3. Server-side sort + filter before pagination.
4. Keep list interactions responsive as filters/sort change.
5. Support debounced real-time search updates without stale-result flicker.

Initial practical targets:

- Default page size: 200
- Max page size: 1000–2000
- Cursor as numeric offset string (v1)

Note:

- Offset pagination is acceptable for v1 and consistent with existing tree endpoint patterns.
- Deep offsets can degrade over very large datasets; keyset pagination can be considered later if needed.

---

## Frontend Implementation Plan

## 1) API client updates

File: `frontend/src/api.js`

- Add `api.filesPage(params, options)` targeting `/files/page`.
- Keep existing `/files` calls untouched.

## 2) App state updates

File: `frontend/src/App.jsx`

Add List View state:

- `viewMode` (`'tree' | 'list'`, default `'tree'`)
- `listItems` (`FileEntry[]`)
- `listCursor` (`string | null`)
- `listHasMore` (`boolean`)
- `listLoading` (`boolean`)
- Dedicated in-flight cancellation ref for List View (`AbortController`)

Add behavior:

- On enter List View: fetch first page.
- On filter/sort/host/category/dups/search inputs changing in List View: reset list and fetch first page.
- On load-more trigger: fetch next page and append.
- Convert `listItems` via existing `fileEntryToRow` and feed `FileTable`.
- Use debounced query state for list searches and cancel stale requests with `AbortController`.
- Keep Tree View search and overlay effects untouched; guard them behind `viewMode === 'tree'` where needed.
- Gate existing tree search effects (`filename`, `hash`, `directory`) behind `viewMode === 'tree'` to avoid overlay activation during List View filtering.

## 3) Header toggle updates

File: `frontend/src/components/Header.jsx`

- Convert top-left `sift` label to a mode toggle control.
- Show current mode text: `Tree View` or `List View`.
- Pass mode-specific helper text to search inputs (placeholder copy) and mode-specific size-filter label.

## 4) Table load-more trigger

File: `frontend/src/components/FileTable.jsx`

Two acceptable v1 options:

1. Reuse existing "Load more" row style.
2. Add near-bottom infinite-scroll callback.

Recommended v1: explicit "Load more" row for simplicity and deterministic fetch behavior.

## 5) Preserve existing tree logic

- Keep all tree fetching, cache, and dup-metrics logic unchanged.
- List View is additive and isolated.
- Gate tree-only effects by `viewMode === 'tree'` so List View search/filter requests do not trigger tree expansion/search side effects.
- Keep duplicate overlay semantics unchanged so click-through duplicate workflows remain reliable.

---

## Backend Implementation Plan

## 1) Add response model(s)

File: `server/models.py`

- Add `FilePageResponse` with:
  - `items: list[FileEntry]`
  - `next_cursor: Optional[str]`
  - `has_more: bool`
- Add `dup_count` (or equivalent duplicate flag) to List View row payload so same-host duplicates can be highlighted correctly.

## 2) Add endpoint

File: `server/main.py`

- Implement `GET /files/page` with validated params.
- Parse `cursor` to numeric offset, reject invalid/negative.
- Parse `hosts`/`categories` comma lists safely.
- Accept `path_contains` and apply case-insensitive path match.
- Build SQL with selected-host scope, optional category filter, duplicate filter, and sortable `ORDER BY` mapping.
- Fetch `limit + 1` to compute `has_more`.
- Return cursor as `offset + limit` when more rows exist.
- Preserve current hash semantics (exact for full hash, contains for partial hash).
- Do not alter existing `/files` query semantics.
- Place `GET /files/page` with the other `/files/*` routes for maintainability.
- For `has_duplicates=true`, perform aggregate readiness check and return `202 pending` if not ready; no grouped fallback query.

## 3) Duplicate filtering path

- Preferred aggregate-backed selected-host duplicate set via `host_hash_stats`.
- If selected-host duplicate aggregates are not fresh/missing, return `202 pending` (no grouped fallback query).
- Keep logic local to `/files/page`; do not alter `/files` semantics.

---

## Test Plan

## Server tests

New file: `tests/server/test_files_page.py`

Cover:

1. Basic paging (`limit`, `cursor`, `has_more`, `next_cursor`).
2. Sorting by each supported column + direction.
3. Host subset filtering via `hosts`.
4. Multi-category filtering via `categories`.
5. `path_contains` matches anywhere in path (case-insensitive).
6. `has_duplicates=true` semantics within selected hosts only.
7. Invalid cursor and invalid sort values return 400.
8. Hash semantics parity with `/files` (64-char exact, partial contains).
9. Existing `/files` test suite remains green.
10. `has_duplicates=true` returns `202 pending` when any selected host aggregate is not fresh.

## Frontend checks

- Verify mode toggle switches sources without tree regression.
- Verify sort/filter/search changes reset list paging and refetch page 1.
- Verify load-more appends rows and preserves order.
- Verify `onlyDups + minDupSize + selectedHosts` interactions match expected semantics.
- Verify debounced typing updates list in real time and cancels stale in-flight requests.
- Verify duplicate overlays (`extra copies`, `uniq dup hashes`) keep current behavior.
- Verify same-host duplicate rows highlight correctly in List View.
- Verify List View intentionally has no dedicated path column in v1 (filename-focused presentation only).

---

## Non-Goals (v1)

- Replacing existing search overlay architecture.
- Unifying Tree View directory-search semantics with List View path filtering.
- Adding a dedicated path column to List View.
- Refactoring all sort/filter state ownership.
- Keyset cursor pagination.
- Backend-side session persistence of List View settings.

---

## Rollout Notes

1. Land backend endpoint + tests first.
2. Land frontend List View toggle + basic load-more.
3. Validate responsiveness on a production-scale dataset.
4. Iterate to infinite-scroll trigger if needed after functional validation.

This gives a low-risk, additive path to List View with scalable performance and no breakage to existing `/files` consumers.
