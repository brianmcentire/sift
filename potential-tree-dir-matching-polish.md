# Potential Tree Directory Matching Polish

## Motivation

Directory search in tree mode currently works well for narrow queries like `tmp`, but broader queries like `users` can produce confusing results when multiple hosts are selected.

Observed bug/rough edge:

- With only `Photoshop-PC` selected, searching for `users` or `tmp` behaves as expected.
- With `Photoshop-PC` and `unraid` both selected, searching for `users` can cause `C:` to disappear from the visible tree while `D:` remains.
- This is especially confusing because the user reasonably expects both `C:/Users` and `D:/Users` to stay visible if they both match.

The current behavior makes the tree feel arbitrary right when the product should feel most trustworthy. Since Sift is for finding needles in a haystack, the UI should optimize for precision and confidence rather than showing every possible path by default.

## Current Root Cause

The current directory-search flow uses a single `/directories` API call and then filters the tree to only matched paths plus their ancestors.

Relevant pieces:

- Frontend search fetch: `frontend/src/App.jsx`
- Tree filtering from `matchedDirPaths`: `frontend/src/App.jsx`
- Server directory search endpoint: `server/main.py` (`/directories`)

What goes wrong:

- `/directories` uses one combined query across all selected hosts.
- The SQL result set is capped with a limit.
- Results are ordered mostly by path relevance/length/path text, not in a way that guarantees fair representation across roots/drives.
- For broad queries like `users`, one drive/root can crowd out another before the frontend even sees the omitted match.
- Once `matchedDirPaths` lacks `__drive__:C/users`, the tree filter removes the `C:` branch entirely.

So this is not really a pure rendering bug; it is a search result selection/presentation problem.

## Product Direction

Do not optimize for full expansion or exhaustive visibility by default.

Instead optimize for:

- showing the best candidate paths quickly
- preserving trust by not silently hiding strong matches
- reducing noisy over-expansion
- keeping the API shape simple for now (single search request)

## Recommended UX Direction

### 1. Compact results, not deep auto-expansion

Default tree behavior should show strong matches with minimal expansion.

- Expand only the ancestor chain needed to reveal a matched directory.
- Do not auto-expand deep descendants under a matched directory.
- Keep the matched directory itself collapsed unless there is a good reason to open it automatically.

Example:

- Searching `tmp` should reveal `C:/ > tmp/` and `/mnt > tmp/`
- It should not explode 10 levels of nested children under `tmp`

This preserves orientation while avoiding the feeling that the tree is fighting the user.

### 2. Show best matches per root

Within a single search response, group matches by visible root:

- `C:/`
- `D:/`
- `/mnt`
- other top-level roots as applicable

Then show only the top 1-3 matches per root by default.

Why this is better than “one match per host/drive tuple”:

- it is predictable
- it avoids one noisy root starving another
- it still gives breadth across the machine set
- it maps better to how users scan the tree visually

Important rule:

- if both `C:/Users` and `D:/Users` are strong matches, both should be visible

### 3. Add overflow affordances instead of silently truncating

When a root has more matches than the compact view shows, render a clear placeholder row such as:

- `+ 6 more matches under C:/`

This is much better than silently dropping results because:

- users know more exists
- the compact presentation feels intentional
- later we can attach lazy loading or expansion-on-click without redesigning the UX

### 4. Prefer breadth over depth

If the UI must cap what is shown, prefer:

- more roots shown
- fewer levels deep per root

In a needle-finding product, breadth is usually more valuable than expanding a single branch far into the tree.

### 5. Add a lightweight search summary

A small summary near the tree could say something like:

- `9 folder matches across 3 roots`

Optional enhancement:

- chips for roots, e.g. `C:/ (3)`, `D:/ (2)`, `/mnt (4)`

This helps users understand that the search result is intentionally condensed rather than incomplete.

## Recommended Naive First Pass

Keep a single `/directories` API call.

After the response returns, do client-side scoring and grouping:

1. convert each result into its UI path
2. compute its root bucket (`C:/`, `D:/`, `/mnt`, etc.)
3. score each result
4. sort within each root by score
5. keep top 2 (or top 3) per root
6. build `matchedDirPaths` from the visible subset
7. expand only ancestor chains for those visible matches
8. render overflow rows when a root has hidden matches

This keeps request count unchanged while making the UI much more intentional.

## Suggested Scoring Heuristics

Good initial scoring inputs:

- exact basename match gets highest priority
  - query `users` strongly favors paths ending in `/Users`
- basename starts-with match ranks next
- shallower paths rank above deeper paths
- shorter overall paths rank above longer paths
- exact query match in normalized case should beat substring-only matches

Possible rough scoring model:

- +1000 exact leaf name match
- +500 leaf starts-with match
- +200 segment contains query
- -10 per path depth
- -1 per path length

This does not need to be perfect. It just needs to be stable and intuitive.

## Important UX Rules

These should hold even in the naive first pass:

- never silently omit an obviously strong match from a root if another root is shown
- do not auto-expand matched nodes deeply
- do not make the user wonder whether a result is missing or simply hidden
- preserve click-to-expand behavior after search results are shown

## Implementation Hints

### Frontend

Likely main touch points:

- `frontend/src/App.jsx`
  - directory search effect
  - `matchedDirPaths` construction
  - `expandedPaths` update logic
  - dir-search row filtering logic
- possibly a small helper in `frontend/src/utils.js`
  - score directory matches
  - derive root key for a UI path
  - group matches by root

Possible helper shapes:

```js
function getUiRootKey(uiPath) {
  if (uiPath.startsWith('__drive__:')) {
    const after = uiPath.slice('__drive__:'.length)
    const slash = after.indexOf('/')
    return slash === -1 ? `${after}:/` : `${after.slice(0, slash)}:/`
  }
  const parts = uiPath.split('/').filter(Boolean)
  return parts.length > 0 ? `/${parts[0]}` : '/'
}

function scoreDirectoryMatch(uiPath, rawQuery) {
  // normalize and score basename exactness, prefix match, depth, path length
}
```

Possible flow inside the directory-search effect:

```js
const uiMatches = dirs.map(d => ({
  ...d,
  uiPath: dirResultToUiPath(d.host, d.drive, d.dir_path, hostMap),
}))

const grouped = groupByRoot(uiMatches)
const visibleMatches = selectTopMatchesPerRoot(grouped, 2)
const overflowByRoot = computeOverflow(grouped, visibleMatches)
```

Potential new state:

- `dirSearchOverflowByRoot`
- maybe `dirSearchSummary`

### Tree rendering

Current filtering logic assumes `matchedDirPaths` is the full set of matches to reveal.

That can stay mostly intact if `matchedDirPaths` becomes the visible compact subset rather than the raw API response set.

Later, overflow rows could be injected similarly to how load-more rows are injected now.

### Server

Not required for the first UX pass, but worth remembering:

- `/directories` currently truncates too aggressively for broad multi-host searches
- a later improvement could fetch more candidates internally before final trimming
- ordering should be deterministic across host/drive ties

Even if frontend compacting is added, server-side starvation of strong candidates is still worth revisiting later.

## Good Defaults To Try First

Recommended starting values:

- top 2 matches per root
- ancestor-only expansion
- matched directories remain collapsed by default
- exact basename matches always survive compacting
- summary text shown when total matches > visible matches

## Future Polishing Ideas

Later, without changing the conceptual UX:

- clicking `+ N more matches under C:/` expands the hidden matches in place
- keyboard navigation across match groups
- a “compact / show all matches” toggle
- lazy loading hidden matches per root
- better ranking informed by recent navigation or path popularity

## Success Criteria

This polish is successful if:

- broad queries like `users` no longer make `C:` appear to vanish arbitrarily
- narrow queries like `tmp` stay fast and readable
- the tree reveals likely needles quickly
- users understand when more matches exist
- no extra API calls are needed for the first pass
