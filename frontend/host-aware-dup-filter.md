# Host-Aware "Only Dups" Filter

## Semantic Contract

The "Only dups" toggle filters the file tree to show only duplicated files. What counts as a "duplicate" depends on which hosts are selected:

- **1 host selected**: only same-host dups (files duplicated within that single host)
- **2+ hosts selected**: same-host dups on any selected host, OR cross-host dups where at least one copy exists on another *selected* host
- **All hosts selected**: all dups (original behavior)

## How `dup_count` and `other_hosts` Interact

| Field | Scope | Description |
|---|---|---|
| `dup_count` | Per-host (server-computed) | Count of same-hash files on the same host. Summed across selected hosts in `mergeEntries`. |
| `other_hosts` | Global (server returns ALL hosts) | Comma-separated list of other hosts that have a file with the same hash. Last-wins in `mergeEntries`. |

The key insight: `dup_count` is already host-scoped (the server computes it per-host, and `mergeEntries` only sums selected hosts). But `other_hosts` is global — it lists ALL other hosts regardless of selection. This means raw `other_hosts` makes files appear as dups even when the "other" host isn't selected.

## Client-Side Filtering Approach

### `hasSelectedOtherHost(otherHosts, selectedHosts)` (utils.js)

Returns `true` if any host in the comma-separated `otherHosts` string is in the `selectedHosts` Set. Used everywhere `Boolean(other_hosts)` was previously used:

- **treeRows memo**: strict dir check, strict file check, minDupSize filter
- **searchRows memo**: onlyDups filter, minDupSize filter
- **FileRow**: `otherHostList` filtered to only include selected hosts, which flows into `isDup` highlight and `allHostsSet` badge display

## Min Dup Size and Dup Highlighting

### Semantic contract

`minDupSize` means "ignore duplicates smaller than this threshold." This applies in two ways:

1. **Filtering**: dups below the threshold are hidden when "Only dups" is active, and in pinned/search views where all results are inherently dups.
2. **Visual highlight**: files below the threshold should NOT get amber/orange dup highlighting in the tree view, even in "All files" mode. If the user says "I don't care about dups below 1K," those files should look like normal (non-dup) files.

### Pinned file copies view

When the user clicks a file to see its copies (`/files?hash=X`), every result shares the same hash — they are all dups by definition. However, `fileEntryToRow` sets `dup_count: 0` on each row (it doesn't know the count). The minDupSize filter's `if (!isDup) return true` short-circuit was incorrectly keeping all rows visible.

Fix: in pinned/search mode, recognize that all results are inherently dups and apply the size filter unconditionally (no `isDup` gate needed).

### FileRow amber highlight

`FileRow` computes `isDup` from `dup_count` and `otherHostList` but has no awareness of `minDupSize`. Fix: pass `minDupSize` through and suppress `isDup` when the file is below the threshold.

### What stays unchanged

- Server endpoints (no API changes)
- `mergeEntries` logic (`dup_count` summing is already correct)
- Lenient expansion (uses `dup_count > 0`, not `other_hosts`)
- Stats bar (already passes `selectedHosts` to server)
- The cached `other_hosts` string (filtered at read time, not write time)
