# sift sets — Hash-Based Set Operations

`sift sets` compares two collections of files by their content hashes to answer
questions like "are all files on this backup disk already somewhere else?"

## Quick Start

```bash
# What's on the backup that isn't in /mnt/backups or /mnt/media?
sift sets /mnt/disks/backup2012 /mnt/backups /mnt/media

# Same question, summary only (no file list)
sift sets /mnt/disks/backup2012 /mnt/backups /mnt/media --summary

# Check if backup is fully covered by the rest of the datastore
sift sets /mnt/disks/backup2012 --covered

# Check against a specific host
sift sets /mnt/disks/backup2012 --covered unraid

# Cross-host comparison
sift sets photoshop-pc:D:/ unraid:/mnt/media/Photos

# Show first 10 missing files with sizes and dates
sift sets /mnt/disks/backup2012 /mnt/backups -l -10
```

## Syntax

```
sift sets [SOURCE] [TARGET ...] [options]
sift sets -a PATH [PATH ...] -b PATH [PATH ...] [options]
sift sets SOURCE --covered [HOST ...] [options]
```

The first positional argument is the **source** (set A). Remaining positionals are
**targets** (set B). By default, the output shows files in A whose hashes are not
found in B — i.e., content that exists only in the source.

## Arguments

| Argument | Description |
|----------|-------------|
| Positionals | First = source (A), rest = targets (B) |
| `-a PATH [PATH ...]` | Explicit source paths (one or more `host:/path`) |
| `-b PATH [PATH ...]` | Explicit target paths (one or more `host:/path`) |
| `--covered [HOST ...]` | B = all hashes in the datastore (optionally limited to listed hosts), excluding source paths |
| `--min-size SIZE` | Ignore files below threshold on both sides (e.g. `1M`, `500k`, `1G`) |
| `-n N` | Limit file list output to N entries |
| `-N` | Shorthand for `-n N` (e.g. `-10` = `-n 10`) |
| `--summary` | Show summary only, suppress file list |
| `--no-summary` | Suppress summary, output file list only |
| `-l` / `--long` | Show size and date in file list |
| `--reverse` | Show B-A instead of A-B (files in target not in source) |
| `--common` | Show A∩B intersection (source files that are covered) |
| `--json` | JSON output to stdout |

### Mutual exclusions

- Positional targets, `-b`, and `--covered` are mutually exclusive for defining B
- `--reverse` and `--common` are mutually exclusive

## Output

### Summary (stderr)

Shown by default. Suppress with `--no-summary`.

```
sift sets: /mnt/disks/backup2012 → /mnt/backups, /mnt/media

  source (A):     15,234 files    145.2 GB   (14,890 unique hashes, 344 unhashed)
  A only:            690 hashes   (   778 files)    12.4 GB
  B only:         45,200 hashes
  A ∩ B:          14,200 hashes   (14,456 files)   132.8 GB   95.4% of A covered
  unhashed:          200 covered by size+mtime, 144 unverifiable

  result: NOT FULLY COVERED — 690 unique hashes only in source
```

### File list (stdout)

Pipeable. Shows A-B by default (files in source not in target).

```
/mnt/disks/backup2012/Photos/vacation2012/IMG_0001.jpg
/mnt/disks/backup2012/Documents/taxes_2012.pdf
```

With `-l` (long format):
```
  4.2M  2012-07-15  /mnt/disks/backup2012/Photos/vacation2012/IMG_0001.jpg
  1.2M  2013-04-10  /mnt/disks/backup2012/Documents/taxes_2012.pdf
```

### Exit codes

- `0` — fully covered (all source hashes found in target, no unverifiable unhashed)
- `1` — not fully covered
- `2` — error (bad arguments, server unreachable, etc.)

## Use Cases

### Backup retirement

Before removing a backup disk, verify every file on it exists somewhere else:

```bash
sift sets /mnt/disks/old-backup --covered --summary
```

If the result is `FULLY COVERED`, the disk can be safely retired. If not, list the
orphan files:

```bash
sift sets /mnt/disks/old-backup --covered
```

### Mirror verification

Confirm two directories are content-identical (same hash sets in both directions):

```bash
sift sets /mnt/original /mnt/mirror --summary
sift sets /mnt/mirror /mnt/original --summary
```

Both should report `FULLY COVERED` if the mirror is complete.

### Finding unique files

List files on a backup disk that don't exist anywhere on a specific host:

```bash
sift sets /mnt/disks/external unraid:/mnt/media -l
```

### Post-migration audit

After migrating data, check nothing was lost:

```bash
sift sets old-server:/data new-server:/data --summary
```

### Pipe to file

Save orphan file list for review:

```bash
sift sets /mnt/disks/backup2012 /mnt/backups --no-summary > orphans.txt
```

## `--covered` Mode

`--covered` defines set B as "all hashes in the datastore, excluding files under
the source path(s)." This prevents a file from being considered covered by itself.

```bash
# vs everything on all hosts
sift sets /mnt/disks/backup2012 --covered

# vs all hashes on a specific host
sift sets /mnt/disks/backup2012 --covered unraid

# vs union of multiple hosts
sift sets /mnt/disks/backup2012 --covered unraid photoshop-pc
```

Source path exclusion ensures that if a file exists **only** on the backup disk, it
won't falsely appear as "covered."

## Unhashed Files

Files without a hash (not yet scanned, permission errors, dataless stubs) get
tiered treatment:

1. **Hashed in one side, unhashed in the other** — treated as different (cannot
   verify content match)
2. **Unhashed in both sides** — secondary check: if the same `(filename, size, mtime)`
   tuple exists in B, considered "covered by size+mtime" (best-effort)
3. **Unhashed in source, no match** — reported as "unverifiable"

The summary reports these separately. Size+mtime matching is only available when B
entries are fully fetched (e.g. with `--reverse`); in streaming mode (default),
unhashed source files are reported as unverifiable.

To minimize unhashed files, run `sift scan` on all relevant paths first.

## Performance

- **Streaming**: Large target sets (e.g. `--covered` across 800k+ files) use a
  streaming `/files/hashes` endpoint (~70 bytes/row) instead of loading full entries
  (~300 bytes/row). Progress is printed to stderr.
- **Memory**: Hash sets are built incrementally from the stream. Even 1M+ files
  use modest memory (~100MB for the hash set).
- **Min-size filter**: Applied server-side on both sides, reducing data transfer.

## Comparison with Other Commands

| Command | Purpose | Comparison basis |
|---------|---------|-----------------|
| `sift diff` | Show path-level differences between two dirs | Filenames (path-based) |
| `sift comm` | Three-column comparison of two dirs | Filenames or hashes (`--hashes`) |
| `sift sets` | Hash set operations across any number of dirs | Content hashes (asymmetric) |

Use `sift diff` or `sift comm` when you care about **where** files are (same name,
same path). Use `sift sets` when you care about **what** content exists regardless
of filename or directory structure.
