# Frontend Improvement Plan

## Objectives

- Keep backend progress intact; focus all near-term work on frontend correctness and responsiveness.
- Preserve stable duplicate/search contracts from:
  - `architecture-principles.md`
  - `search-interaction-contract.md`
  - `duplicate-semantics.md`
- Remove/avoid frontend fallbacks that can show incorrect rows while data is still loading.

## Product Rules To Enforce

- `Min size` is unified (not split between "dup" vs "file" meanings).
- `Min size` applies to files across Tree, List, and overlay/result views.
- Category filters apply to files across Tree, List, and overlay/result views.
- Hash-search result overlays are the only mode that bypasses size/category filters.
- In Tree + `Only dups`, file rows must never appear unless duplicate eligibility is established.
- If duplicate metrics are pending, keep directory/context continuity but do not leak unverified file rows.

## API-Driven Frontend Contract

- Tree structure: `GET /tree/children` (bounded, paged).
- Tree duplicate metrics: `GET /tree/dup-metrics` (selected-host aware; authoritative for dup eligibility).
- List view inventory: `GET /files/page` (server-side paging/sort/filter).
- Duplicate click-through overlays: `GET /files/duplicates-by-subtree-hashes` (`scope=subtree|context`).
- Directory-search expansion: `GET /directories`.

Notes:
- Treat `/tree/children` duplicate fields as non-authoritative until `/tree/dup-metrics` enrichment arrives.
- Prefer server-authoritative paths over client-side fallback reconstruction.

## Implementation Sequence

1. Fix Tree `Only dups` leak first.
   - Separate directory visibility from file visibility in tree filtering.
   - Stop pending-metrics logic from preserving unverified file rows.

2. Make Tree load-more metric-safe.
   - In Tree + `Only dups`, do not render newly paged file rows until duplicate eligibility is known.
   - Keep navigation continuity with directories/context while metrics are pending.

3. Unify `Min size` semantics in frontend behavior.
   - Apply as a universal file filter in Tree/List/overlay modes.
   - Preserve hash-search bypass exception.

4. Confirm category consistency in Tree/List/overlay modes.
   - Category filters constrain file rows in all modes.
   - Tree may keep minimal directory context but must not leak invalid file rows.

5. Re-verify duplicate click-through contract behavior.
   - Directory `X uniq dup hashes` text action.
   - Directory context/list icon action.
   - File `Y extra copies` text action.
   - File context/list icon action.

6. Remove remaining legacy fallback paths in small follow-ups.
   - Only after Step 1-5 are stable.

## Short Implementation Checklist

- [ ] Repro baseline bug:
  - Host: `brians-m2prombp`
  - `Only dups` enabled
  - `Min size` = `100MB`
  - Scroll deep and confirm current leak repro path behavior.

- [ ] Patch tree filtering so pending metrics never allow unverified file rows in Tree + `Only dups`.

- [ ] Patch load-more path so newly loaded file rows in Tree + `Only dups` remain hidden until duplicate eligibility is available.

- [ ] Validate regression checks:
  - No non-dup file leaks in the repro scenario.
  - Directory dup badge click-through still correct.
  - File click overlay and back behavior still correct.
  - Hash-search overlays still bypass size/category filters.

- [ ] Validate unified filter behavior:
  - `Min size` filters file rows in Tree/List/overlays.
  - Category filters apply in Tree/List/overlays.
  - Hash-search result overlays remain the exception.

- [ ] Document any remaining fallbacks and either remove them or track explicit reasons to keep.
