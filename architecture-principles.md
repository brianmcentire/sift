# Architecture Principles

This document captures stable architectural principles for sift.

Code is authoritative for current behavior and contracts, except where behavior is clearly a bug.

## Prime Directive

- Prefer bounded, incremental work over global scans/recomputations.
- Do not introduce global locks or heavy DB operations on hot paths unless strictly necessary.
- Reuse existing endpoints/contracts first; add or replace endpoints only for clear, measured benefit.
- Treat frontend responsiveness as a first-class constraint; avoid changes that materially degrade interaction latency or perceived UI smoothness.
- If a proposed change materially impacts performance, safety, or operational posture, pause and ask before proceeding.

## Canonical References

- Product behavior and user-facing features: `README.md`
- Duplicate semantics source of truth: `duplicate-semantics.md`
- Search/filter interaction contract: `search-interaction-contract.md`
- Live API endpoint contract (implemented routes and params): `server/main.py`

## Core Principles

- Hash locally, not over network mounts.
  - Scanning hosts compute hashes on-host and send metadata/results to the server.
- Keep database ownership on the server.
  - Agents and clients must not write to the DB directly.
- Preserve idempotent ingestion.
  - Retries and repeated submissions should be safe and converge on the same stored state.
- Normalize paths at ingest.
  - Store normalized keys for matching/querying and display forms for UI.
- Store absolute paths.
  - Relative invocation must not produce relative storage.
- Support partial scans safely.
  - Scan scope updates only that scope; out-of-scope data remains untouched.

## Data Freshness and Presence

- Treat "seen" updates and full upserts as separate concerns.
  - Unchanged files should update presence efficiently without unnecessary rehash.
- Use scoped tombstoning semantics.
  - Absence detection is bounded to the host + scanned root context.
- Keep clock comparisons safe.
  - Presence/tombstone logic should compare timestamps produced from compatible clocks/context.

## Performance and Safety

- Prefer incremental work over full recomputation.
  - Reuse mtime/size-based change detection and cached aggregates where available.
- Avoid global locks and heavy DB operations on hot paths.
  - If unavoidable, treat as exceptional and justify explicitly before implementation.
- Keep duplicate analysis read-only by default.
  - Any future action workflow (delete/move/reference) must be designed as a separate safety boundary.

## Exclusion and Classification Policy

- Apply exclusion rules at scan time.
  - Directory/path/file exclusions and volatile-file handling belong in agent scan policy.
- Classify conservatively.
  - Prefer correct broad categories over aggressive or speculative typing.

## Evolution Rules

- If docs conflict, prefer tested code behavior and update docs promptly.
- Keep this file principle-level.
  - Do not turn it into a backlog, migration plan, or endpoint-by-endpoint spec.
- When changing semantics/contracts, update the canonical references in the same change.
