# sift report

Temporary design + implementation tracker for `sift report`.

Delete this file once `sift report` is fully implemented and documented in durable locations.

Code remains authoritative except for bugs.

## Goal

Add a single CLI command, `sift report`, that produces a useful all-host datastore report with:

- inventory totals
- duplicate/extra-copy summary (using locked semantics below)
- host-only duplicate summary
- cross-host redundancy focus
- tombstone pressure summary
- data-driven file-size clustering (k=10)
- top duplicate opportunities ranked by extra bytes

No initial user parameters are required. One command, one report.

## Locked Decisions

- Command is `sift report` (no initial flags required).
- Scope is all hosts currently in datastore.
- Terminology uses `uniq dup hashes` (not "duplicate sets").
- "Extra" wording is used (`extra copies`, `extra bytes`), not "wasted".
- Global duplicate summary scope is **union** of:
  - intra-host duplicates, and
  - cross-host duplicates with `>= 3` total copies across `>= 2` hosts.
- Union scope must deduplicate overlaps (a hash counted once globally).
- Host-only table semantics:
  - `extra copies` per host = strictly intra-host `(copy_count_effective - 1)`.
  - rows sorted by hostname (alpha ascending).
  - include `extra bytes (%)`, where `% = extra_bytes / host_total_bytes`.
  - percentages show at most one decimal; trailing `.0` may be omitted.
- Top opportunities section is restricted to the same global summary scope.
- Tombstone section focuses on rows/files first (bytes second).
  - `top host by tombstone files`, not by bytes.
  - if hosts with tombstone pressure are `<= 5`, list names.
  - if all hosts have pressure, show `all X`.
  - otherwise show numeric count.
- File-size clustering uses log-space k-means with median-size reporting.
  - target `k=10`.
  - only use fewer clusters with a compelling statistical reason.
- Report output should show meaningful progress with step count (`x/y`) and aligned columns.

## Output Contract (Mock)

```text
$ sift report

sift server: http://192.168.1.200:8765
sift 0.9.1  ·  report scope: all hosts in datastore

Building report: [1/7] inventory totals ................... done (0.2s)
Building report: [2/7] duplicate aggregates ................ done (0.4s)
Building report: [3/7] host-only extra copies .............. done (0.2s)
Building report: [4/7] cross-host (3+ copies, 2+ hosts) .... done (0.3s)
Building report: [5/7] tombstone pressure .................. done (0.2s)
Building report: [6/7] file-size clustering (k=10) ......... done (1.1s)
Building report: [7/7] top duplicate opportunities ......... done (0.2s)

Inventory Summary
-----------------
hosts in datastore : 4
total file rows    : 22,104,882
total bytes        : 96.3 TB
zero-byte files    : 182,441 (0.8%)

Duplicate Summary (Global Criteria)
-----------------------------------
criteria: extra copies from intra-host duplicates + cross-host duplicates
          with >=3 total copies across >=2 hosts

uniq dup hashes                                   : 611,942
extra copies (cross-host 3+ and intra-host)      : 3,332,178
extra bytes  (cross-host 3+ and intra-host)      : 11.8 TB
gross duplicate bytes (same scope)               : 15.9 TB

Host-Only Extra Copies
----------------------
host             uniq dup hashes    extra copies    extra bytes (%)
---------------  -----------------  --------------  ----------------
Brians-M2ProMBP  188,304            412,901         1.9 TB (1.8%)
Unraid           402,119            901,442         4.3 TB (2%)
bedroompi        2,118              4,020           11.2 GB (9.4%)
rpi3b            1,967              3,872           9.8 GB (1.1%)

Cross-Host Redundancy Focus
---------------------------
criteria: >=3 total copies and present on >=2 hosts

qualifying uniq dup hashes                         : 247,311
qualifying file copies                             : 1,486,207
extra copies in scope                              : 1,238,896
extra bytes in scope                               : 6.7 TB
gross duplicate bytes in scope                     : 9.4 TB

Tombstone Pressure
------------------
definition: rows currently eligible for `sift trim --deleted` under
            covering complete-scan rules

eligible tombstone rows                            : 842,110
eligible tombstone bytes                           : 780.4 GB
hosts with tombstone pressure                      : Unraid, bedroompi, rpi3b
top host by tombstone files                        : Unraid (501,220)

File-Size Clusters (Data-Driven, k=10)
--------------------------------------
cluster  median size    files         pct of files
-------  -------------  ------------  ------------
C1       0 B            182,441       0.8%
C2       1.8 KB         1,721,003     7.8%
C3       9.6 KB         4,998,221     22.6%
C4       54.3 KB        5,841,773     26.4%
C5       412.0 KB       4,320,114     19.5%
C6       2.7 MB         2,241,008     10.1%
C7       15.9 MB        1,572,603     7.1%
C8       97.4 MB        872,901       3.9%
C9       612.0 MB       297,887       1.3%
C10      3.2 GB         56,931        0.3%

Top Duplicate Opportunities (Ranked by Extra Bytes)
---------------------------------------------------
rank  extra bytes  copies  hosts  type     sample filename
----  -----------  ------  -----  -------  -----------------------------
1     84.2 GB      14      3      video    Movie.Title.2001.2160p.mkv
2     61.7 GB      9       2      archive  photos-archive-2022.tar
3     55.1 GB      11      2      video    series.s01.complete.mkv
4     48.3 GB      20      4      image    IMG_202108_BackupSet.zip
5     43.9 GB      6       2      video    documentary.collection.mkv
```

## Implementation Plan (Checklist)

Use this as the execution tracker. Mark items complete as they are finished.

### 1) CLI command wiring

- [ ] Add `report` subcommand in `sift/main.py`.
- [ ] Implement `sift/commands/report.py` entrypoint (`cmd_report`).
- [ ] Ensure output style matches existing CLI conventions (server info, spacing, stderr/stdout usage).

### 2) Data query contract (server-side)

- [ ] Add one report endpoint that returns all report sections in one payload (preferred for consistency).
- [ ] Keep query paths aggregate-first (`host_stats`, `host_hash_stats`, `hash_stats`, `scan_runs`) and avoid heavy fallback on hot paths.
- [ ] Implement global union-scope duplicate math with strict hash de-dup across overlap.
- [ ] Implement host-only table semantics from locked decisions.
- [ ] Implement tombstone-pressure section using existing `trim --deleted` eligibility logic.
- [ ] Implement clustering payload: log-space k-means with target `k=10`, cluster medians + counts + percentages.
- [ ] Implement top opportunities list restricted to global summary scope and ranked by extra bytes.

### 3) Progress and formatting

- [ ] Add stepwise progress renderer (`[x/y]`) in CLI for report generation.
- [ ] Align/justify all tabular and key-value output consistently.
- [ ] Normalize percent formatting (max 1 decimal, trim trailing `.0`).
- [ ] Validate host sorting (alpha) in host-based tables.

### 4) Validation and tests

- [ ] Add server tests for summary semantics, union de-dup, host-only semantics, and tombstone-host display rules.
- [ ] Add tests for clustering payload shape and deterministic behavior on a synthetic fixture.
- [ ] Add CLI output tests for alignment-sensitive sections (or robust golden-file style checks).
- [ ] Run full relevant test suites and verify no regressions in existing endpoints.

### 5) Documentation cleanup

- [ ] Add/refresh durable user docs (README or command help) for `sift report` once implemented.
- [ ] Remove this file (`sift-report.md`) after implementation + docs are complete.

## Notes

- No implementation starts from this file alone; this is design + checklist only.
- If semantics drift during implementation, update this file first, then code, then tests.
