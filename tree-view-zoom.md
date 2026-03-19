# Subtree Re-Root Feature

## Context
Users browsing large directory trees want to "zoom in" to a subtree without losing their place. Shift-clicking a directory replaces the tree view with that directory as the new root, and a back button steps out. This is nestable — shift-click deeper to build a stack. Filters, dir search, and filename search are scoped to the subtree. Hash search remains global. Stats reflect the subtree.

## Files to Modify

| File | Change |
|------|--------|
| `frontend/src/components/FileRow.jsx` | Pass click event to `handleRowClick`, detect `shiftKey`, call `onReRoot` |
| `frontend/src/components/FileTable.jsx` | Thread `onReRoot` prop to `FileRow` |
| `frontend/src/App.jsx` | New state, handlers, banner, scoped search/stats |
| `server/main.py` | Add `path_prefix` param to `/stats/overview` and `/files/ls` |

## Implementation Steps

### 1. FileRow.jsx — Detect shift-click on directories

- Change `onClick={handleRowClick}` → `onClick={e => handleRowClick(e)}`
- Update `handleRowClick` to accept event param:
  ```js
  function handleRowClick(e) {
    if (isDir) {
      if (e?.shiftKey && onReRoot) {
        onReRoot(fullPath, { driveContext, isDriveNode: entry.isDriveNode, driveLabel: entry.driveLabel })
      } else {
        onToggleDir(fullPath, { driveContext, isDriveNode: entry.isDriveNode, driveLabel: entry.driveLabel })
      }
    } else {
      onFileClick?.(entry, fullDisplayPath)
    }
  }
  ```
- Add `onReRoot` to destructured props (line ~126 area)

### 2. FileTable.jsx — Thread `onReRoot` prop

- Accept `onReRoot` in props (line ~32)
- Pass to `<FileRow onReRoot={onReRoot} .../>` (line ~203)

### 3. App.jsx — State & handlers

**New state:**
```js
const [viewRootStack, setViewRootStack] = useState([])
// Each entry: { path, expandedPaths, activeDrive }
```

`currentPath` (line 21, already `useState('/')`) becomes the active root — mutated on re-root.

**`handleReRoot(fullPath, opts)` handler:**
1. Push `{ path: currentPath, expandedPaths: new Set(expandedPaths), activeDrive }` onto `viewRootStack`
2. If drive node (`opts.isDriveNode`):
   - `setCurrentPath('/')`, `setActiveDrive(opts.driveLabel)`
   - The children are already cached at `${host}:${driveLabel}:/`
   - `buildRows` needs a small tweak: when `viewRootStack.length > 0` and `activeDrive` is set,
     skip the multi-drive synthetic node injection and render the single drive's root entries directly
     (similar to the noDriveHosts branch but using `activeDrive` to pick cache keys)
3. If regular dir:
   - `setCurrentPath(fullPath)`, preserve current `activeDrive`
   - `fetchPath(fullPath, activeHosts, { enrichDupMetrics: true, drive: opts.driveContext })`
4. `setExpandedPaths(new Set())` — start fresh in subtree
5. Clear any active overlay (`pinnedResults`, `subtreeDupPath`, etc.) and `overlayBackStack`

**`handleReRootBack()` handler:**
1. Pop last entry from `viewRootStack`
2. `setCurrentPath(popped.path)`
3. `setExpandedPaths(popped.expandedPaths)`
4. `setActiveDrive(popped.activeDrive)`
5. Clear active overlays

**Update `reset` (line 984):** Add `setCurrentPath('/')` and `setViewRootStack([])`

### 4. App.jsx — Re-root banner

When `viewRootStack.length > 0`, render a persistent banner **above** the overlay banner (if any):
```jsx
{viewRootStack.length > 0 && (
  <div className="...">
    <button onClick={handleReRootBack}>← Back</button>
    <span>Viewing: {currentPath}</span>
  </div>
)}
```

This is a separate layer from the overlay `searchBanner` — both can be visible simultaneously. The re-root banner is always on top; the overlay banner is below it. They have independent back actions.

### 5. App.jsx — Scope dir search to subtree

Dir search `useEffect` (fetches from `/directories`): when `currentPath !== '/'`, filter results client-side — discard any result whose `uiPath` doesn't start with `currentPath + '/'`. This avoids a server change to `/directories`.

### 6. App.jsx — Scope filename search to subtree

Filename search calls `api.files({ filename: ... })`. Add `path_prefix: currentPath` when `currentPath !== '/'`. Check if `/files` endpoint already accepts `path_prefix` — if not, add it server-side. (The `/files` endpoint likely already supports `path` filtering; verify during implementation.)

### 7. Server — Scope `/stats/overview` to subtree

Add `path_prefix: str = Query("")` parameter to `/stats/overview` (line ~3116).

When `path_prefix` is non-empty:
- Replace `host_stats`-based total query with live query on `files` table filtered by `path LIKE lower(path_prefix) || '/%'`
- Scope dup computation to files within the prefix
- Include `path_prefix` in the existing response cache key

This is heavier than the pre-aggregated path but acceptable for an interactive action. The existing 5-second stats cache absorbs re-renders.

### 8. App.jsx — Scope stats fetch to subtree

In stats `useEffect` (line 267): when `currentPath !== '/'`, pass `path_prefix: currentPath` to `api.stats()`.

Add `currentPath` to the useEffect dependency array.

### 9. Server + Frontend — Subtree dup highlighting

When zoomed into a subtree, files should visually distinguish between dups that exist
within the subtree vs. dups that only exist outside it.

**Colors:**
- Light orange (`bg-orange-100`): file has duplicate copies **within** the zoomed subtree
- Yellow (`bg-amber-50`): file has duplicates, but all copies are **outside** the subtree
- No highlight: not a duplicate

**Server change (`/files/ls`):**
Add optional `subtree_path: str = Query("")` parameter. When non-empty, compute an additional
`subtree_dup_count` field per file row: count of other copies of the same hash that also fall
under `subtree_path`. This parallels the existing `dupes` CTE but adds a path prefix filter.

The existing `dupes` CTE already computes `dup_count` (copies across selected hosts). Add a
sibling CTE `subtree_dupes` that restricts to `path LIKE lower(subtree_path) || '/%'`:
```sql
subtree_dupes AS (
  SELECT hash, COUNT(*) - 1 AS subtree_dup_count
  FROM files
  WHERE host IN (...) AND path LIKE lower(?) || '/%'
    AND COALESCE(size_bytes, 0) >= ?
  GROUP BY hash
  HAVING COUNT(*) > 1
)
```
Join `subtree_dupes` into the final SELECT, defaulting to 0 when no match.

Return `subtree_dup_count` in `LsEntry` response model (default 0, only populated when
`subtree_path` is provided).

**Frontend change (App.jsx):**
When zoomed (`viewRootStack.length > 0`), pass `subtree_path: currentPath` to `/files/ls`
calls made by `fetchPath`.

**Frontend change (FileRow.jsx):**
Update highlight logic:
```js
const isSubtreeDup = entry.subtree_dup_count > 0
const isExternalOnlyDup = isDup && !isSubtreeDup
// isSubtreeDup → bg-orange-100
// isExternalOnlyDup → bg-amber-50
```

**When not zoomed:** `subtree_path` is empty, `subtree_dup_count` is always 0, highlight
logic falls back to existing yellow-only behavior. No behavior change for non-zoomed views.

### 10. No change to hash search

Hash search is NOT scoped to the re-root — per requirement, hash results remain global within host scope.

### 11. Filter persistence (localStorage)

Do NOT persist `viewRootStack` or `currentPath` in localStorage. Re-root is a transient navigation state — on page reload, start from root `/`. This avoids confusing users who close and reopen the tab.

### 12. Multi-drive host re-root

Shift-clicking a drive node (e.g., `C:`) re-roots to that drive. Implementation:
- `currentPath` stays `/`, `activeDrive` set to the drive letter
- Add a `viewRootDrive` guard in `buildRows`: when `viewRootStack.length > 0 && activeDrive`, skip multi-drive synthetic node injection. Instead, render the single drive's root entries at depth 0 using the `${host}:${activeDrive}:/` cache keys (reuse the existing entry-building pattern from lines 1494-1513 but without the `__drive__:` prefix namespace on paths, since we're "inside" that drive now)
- Banner shows "Viewing: C:" instead of a path
- Dir search, filename search, stats: scope to `drive=activeDrive` params (already supported by most endpoints)

## Interaction Summary

| Action | Behavior |
|--------|----------|
| Shift-click dir | Push current root + expanded + activeDrive to stack, re-root to clicked dir |
| Shift-click drive node | Same as above, sets activeDrive and shows drive's root entries |
| ← Back (re-root banner) | Pop stack, restore previous root + expanded state |
| ← Back (overlay banner) | Pop overlay stack only (re-root unchanged) |
| Reset | Clear everything including re-root stack, return to `/` |
| Dir search | Results filtered to current subtree |
| Filename search | `path_prefix` sent to API, scoped to subtree |
| Hash search | Unchanged — global within host scope |
| Stats bar | Shows subtree-scoped stats via `path_prefix` param |
| Overlays (file click, dup click) | Work normally within re-rooted view |
| Dup highlight (zoomed) | Orange = dup within subtree, yellow = dup outside subtree only |
| Dup highlight (not zoomed) | Yellow only (existing behavior unchanged) |
| List view | Unaffected by re-root (tree-only concept) |

## Verification

1. **Manual testing:**
   - Shift-click a directory → tree re-roots, banner appears
   - Shift-click deeper → nestable, back steps out one level
   - Shift-click a drive node (C:) → re-roots to that drive, banner shows "Viewing: C:"
   - Click back repeatedly → returns to `/`
   - Reset → clears re-root stack entirely
   - Dir search while re-rooted → only subtree results
   - Filename search while re-rooted → only subtree results
   - Hash search while re-rooted → global results (unchanged)
   - Stats bar → reflects subtree totals
   - Open overlay while re-rooted → overlay back returns to re-rooted tree
   - Filters (onlyDups, minSize, categories) → work within subtree
   - Dup file with copies inside subtree → light orange highlight
   - Dup file with copies only outside subtree → yellow highlight
   - Non-zoomed view → yellow only (no regression)

2. **Existing Playwright tests:** `make test-e2e` — run to verify no regressions

## Post-Implementation Doc Updates

### `search-interaction-contract.md`
- § Input Semantics: note that dir search and filename search are scoped to subtree when re-rooted; hash search stays global
- § Modes: Tree View can be in a "re-rooted" state (transient modifier, not a separate mode)
- § Reset Contract: add "clears re-root stack, returns to `/`"
- § Invariants: re-root back and overlay back are independent navigation layers

### `duplicate-semantics.md`
- § Overlay Color Semantics: add zoomed-view dup colors — orange (`bg-orange-100`) for within-subtree dups, yellow (`bg-amber-50`) for external-only dups
- § Non-Negotiable Invariants: add "subtree-scoped dup highlighting must distinguish internal vs external dups when zoomed"

### `README.md`
- § Web UI Features: add bullet for shift-click subtree zoom, back navigation, scoped search/stats, dup color distinction
