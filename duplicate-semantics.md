# Duplicate Semantics Source of Truth

This document is the authoritative semantic contract for duplicate behavior in UI and API paths.
If other docs conflict, this doc and tested code behavior win.

## Prime Directive

- Never implement duplicate-feature changes that introduce global locks or heavy DB operations unless absolutely necessary.
- If such an approach seems necessary, stop and ask before proceeding.
- Prefer existing endpoints and query paths over adding new ones.
- If adding/replacing an endpoint appears to provide clear performance or correctness benefit, ask before proceeding.

## Guiding Principles

- Duplicate eligibility is computed within the selected host scope.
- Directory duplicate metrics are for navigation/presence, not removable-copy math.
- File duplicate metrics are for redundancy/copy math.
- Scope semantics must remain stable even when selected hosts do not all contain the clicked path.

## Core Terms

- Duplicate hash: a hash with more than one effective copy in selected hosts, honoring size threshold.
- Subtree seed hash set for directory `P`: duplicate hashes with at least one member at `P` or below.
- Size threshold: backend `min_size`; UI currently labels this as "min dup size" in some places.
  - Semantics are intentionally phrased so a future UI rename to "min size" does not change this contract.

## Directory vs File Semantics

- Directory hash column label: `X uniq dup hashes`.
- Meaning of `X`: count of distinct duplicate hashes present in that directory subtree.
- File hash column label: `Y extra copies`.
- Meaning of `Y`: redundant copies for that file in selected-host scope.
- Do not use `extra copies` on directories.

## Tree Click Semantics

Directory rows expose two adjacent actions that intentionally differ:

1) Click `X uniq dup hashes` text
- Uses `/files/duplicates-by-subtree-hashes` with `scope=subtree`.
- Human meaning: "show duplicate files that are in this folder tree."
- Result set is path-filtered to the clicked subtree.

2) Click list icon (`☰`)
- Uses `/files/duplicates-by-subtree-hashes` with `scope=context`.
- Human meaning: "start from duplicates found in this folder tree, then show all copies of those duplicates across selected hosts."
- Result set is not path-limited; rows include `in_subtree` to mark which copies are inside the clicked subtree.

File rows also expose two adjacent actions that intentionally differ:

1) Click `Y extra copies` text
- Uses `/files/duplicates-by-subtree-hashes` with `scope=subtree` and `path_prefix` set to the clicked file path.
- Human meaning: "show selected-host duplicate rows for this clicked file path context."
- Result set is path-filtered to the clicked file path context and remains aligned with selected hosts/min size/category filters.

2) Click list icon (`☰`)
- Uses hash-based context lookup (`/files` by hash).
- Human meaning: "show all files for this hash within the current active context filters."
- Context includes current host selection, size floor, and category filter(s) when specified (otherwise all categories).

## API Contract Notes

### `GET /files/duplicates-by-subtree-hashes`

- Required scope inputs: `hosts`, `path_prefix`.
- Duplicate eligibility uses selected hosts and `min_size`.
- Seed hash set honors `path_prefix`, selected hosts, optional category filter, and optional drive filter.
- `scope=subtree`:
  - rows restricted to subtree path
  - when drive is provided, rows also restricted to that drive
- `scope=context`:
  - rows include all selected-host members for seeded hashes
  - when drive is provided, drive limits seeding only (not returned members)
- Returns HTTP `202` with `{status:"pending"}` when any selected-host aggregate freshness is not `fresh`.

### `GET /files/duplicates-by-subtree-hashes/count`

- Returns `uniq_hash_count` for the same seeded hash semantics as above.
- Must stay semantically aligned with the list endpoint for identical filters.

### `GET /tree/dup-metrics`

- Primary selected-host mode uses `hosts` CSV.
- Single-host mode uses `host` when `hosts` is empty.
- Current code behavior: if both are provided, non-empty `hosts` path is used.
- In selected-host mode, stale aggregate freshness returns `data_freshness="stale"` with empty metrics.
- Directory row `dup_hash_count` from this endpoint drives `X uniq dup hashes` visibility/labeling.

## Non-Negotiable Invariants

- "Only dups" must keep directories that lead to duplicate hash sets navigable.
- Context results must preserve in-subtree highlighting via `in_subtree`.
- Host selection changes must invalidate/re-key duplicate metric caches.
- Terminology must remain consistent:
  - directories: `uniq dup hashes`
  - files: `extra copies`

## Freshness

Aggregate tables (`hash_stats`, `host_hash_stats`, `directory_index`) are
refreshed by the background maintenance worker, which is enabled by default.
After a scan or trim completes, affected aggregates are marked `stale` and
queued for refresh; the worker picks them up after 120s of API idle time.

- Per-host aggregates (`host_hash_stats`) are refreshed inline at scan completion.
- Global aggregates (`hash_stats`, `directory_index`) are deferred to the maintenance queue.
- `sift status` shows `dup stats stale` or `dup stats building` in the summary line when any aggregate is not fresh. `sift status -v` shows per-aggregate detail.
- Endpoints handle staleness per their contracts: `/files/duplicates-by-subtree-hashes` returns HTTP 202; `/tree/dup-metrics` returns `data_freshness: "stale"` with empty metrics; `/stats/overview` includes `data_freshness` in response.
- Disable the worker with `SIFT_MAINTENANCE_ENABLED=0` if needed; aggregates will stay stale until re-enabled or manually triggered via `POST /maintenance/run-now?force=true`.

## Forward-Compatibility Flags

- Scope naming: `context` is accepted but vague; if renamed later, update this doc and API/docs together.
- Size filter UI naming may shift from "min dup size" to "min size"; backend `min_size` semantics remain the contract.
- If `/files/duplicates-by-subtree-hashes/count` is folded into another endpoint, preserve seeded-hash parity guarantees and update this doc immediately.
