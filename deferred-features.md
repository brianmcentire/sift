# Deferred Features

Features intentionally left for future development.

---

## `sift dups`
Duplicate analysis command: top wasted space, breakdown by category, host intersection/difference.

## `sift purge`
Safe interactive deletion of confirmed duplicates.

## `sift shell`
REPL with `cd`/`ls`/`find` against the inventory. Includes `rm` for removing inventory entries (not files).

---

## Server: `is_scanning` field on `/hosts`

**Context:** `last_scan_at` in `/hosts` is derived from `MAX(started_at)` on `scan_runs` filtered to
`status = 'complete'` only. A host mid-scan has no completed runs, so `last_scan_at` is NULL.

**Deferred fix:** Add `is_scanning: bool` to the `HostEntry` response model — a simple
`EXISTS (SELECT 1 FROM scan_runs WHERE host = ? AND status = 'running')` per host. The web UI
could then show a scanning indicator, and the CLI could use it directly rather than
cross-referencing scan runs.

**Current workaround:** CLI cross-references the `/scan-runs` response to detect running scans
and displays "scanning..." in the last scan column.
