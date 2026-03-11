# Plan: Revert frontend regressions, then re-apply tree-leak fix

## Context

Multiple accumulated frontend changes from recent sessions have introduced a regression:
clicking a directory's "X uniq dup hashes" badge now returns "No duplicate hashes matched
selected hosts for this directory at current min size" — confirmed to only happen with
the pending changes, not on the committed version. No category filter is active.

The changes interact in ways that are hard to isolate by code analysis alone:
- `dupMetricSegmentsRef` refactor changes how "Only dups" decides if metrics are loaded
- Auto-load + limit bump cause more tree data + metric fetches to happen concurrently
- The combination may cause stale `dup_hash_count` values to persist in the cache,
  making dirs show dup badges that don't correspond to actual results

Per architecture-principles.md: "Treat frontend responsiveness as a first-class constraint;
avoid changes that materially degrade interaction latency or perceived UI smoothness."
Per duplicate-semantics.md: "Duplicate click-through flows remain reliable and
semantically correct." The current state violates both.

## Step 1: Revert ALL frontend changes

Restore committed versions of all three frontend files:

```bash
git checkout HEAD -- frontend/src/App.jsx frontend/src/components/FileTable.jsx frontend/src/api.js
```

This reverts:
- `setPinnedResults([])` in `handleFileClick` (my change)
- `dupMetricSegmentsRef` refactor in "Only dups" filtering (prior session)
- Auto-load "Load more" on scroll (FileTable.jsx)
- Tree children limit 200 → 500 (api.js)

**Keep** server-side changes (db.py, server.py) — DB lock handling is unrelated.

### Verification after revert
1. `make build-frontend`
2. Enable "Only dups" + min size
3. Click directory dup badges → should work (no "No duplicate hashes" error)
4. Confirm baseline is restored

## Step 2: Re-apply ONLY the tree-leak fix

After confirming the baseline is clean, add back the one-line fix for the original
tree-leak bug (tree rows showing through during file-click search):

**`frontend/src/App.jsx` — `handleFileClick`:**
Add `setPinnedResults([])` before the `await`.

This is correct per search-interaction-contract.md:
> "Active overlay/search result set takes precedence over plain tree rows."

It enters overlay mode instantly on click, hiding the tree. The brief empty table
(~100-200ms) is correct behavior — far better than stale tree rows leaking through.

### Verification after re-apply
1. `make build-frontend`
2. Click any file → search results appear immediately, no tree leak
3. Click "← Back" → tree restores
4. Click directory dup badges → still works (no regression)
5. Test with "Only dups" + min size active

## Files to modify
1. `frontend/src/App.jsx` — revert to HEAD, then add `setPinnedResults([])` only
2. `frontend/src/components/FileTable.jsx` — revert to HEAD
3. `frontend/src/api.js` — revert to HEAD

## What's NOT re-applied (deferred for separate investigation)
- `dupMetricSegmentsRef` refactor — needs deeper analysis of metric cache invalidation
- Auto-load "Load more" — useful UX but may need to be decoupled from dup metric timing
- Limit 200→500 — benign but reverting for clean baseline
