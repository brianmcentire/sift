# Virtual Hosts & Host Management

In sift, a **host** is any named source of file inventory — a machine, an
external disk, a NAS share. Most hosts correspond to always-on machines that
scan regularly, but sift also supports **virtual hosts**: named identities for
external or offline media that may be scanned once and then disconnected.

This document is the design contract for virtual host creation, host visibility
management, and the `sift host` subcommand.

## Motivation

External drives, retired backup disks, and infrequently connected machines all
contain valuable inventory data. Knowing what's on them enables:

- **Backup retirement**: verify every file on an old disk exists elsewhere
  (`sift sets old-disk:/ --covered`)
- **Coverage audits**: confirm nothing was lost in a migration
- **Rediscovery**: find a file you forgot was on a shelf drive

But this data shouldn't clutter the daily view. A user with 2 active machines
and 8 shelf drives shouldn't see 10 host chips every time they open the UI.

## Core Concepts

### Virtual hosts (`--as`)

When scanning media that isn't a permanent machine, use `--as` to assign a
descriptive name that becomes the host identity in the datastore:

```bash
sift scan /mnt/disks/backup --as laptop-backup-2018
sift scan E:\ --as photo-pc-d-2013
```

**Naming convention**: pick a name that describes the media, not the machine
it's plugged into. The name is a permanent ID — keep it short, descriptive,
and avoid spaces. Use `sift host label` for longer human-readable descriptions.

Good names:
- `laptop-backup-2018` (what it is + when)
- `Photo-PC-D-2013` (origin machine + drive + era)
- `WD-1TB-Family-Photos` (physical label + content)

Avoid:
- `external-drive` (too generic, won't scale)
- `unraid:/mnt/disks/disk5` (ties the name to a transient mount)

### Scan root (`--root`)

Virtual hosts need a **scan root** — the mount point prefix to strip so that
stored paths reflect the disk's own directory structure, not wherever it
happened to be mounted.

`--root` is required when `--as` is used. If omitted from the command line,
sift prompts interactively:

```bash
sift scan /mnt/disks/backup --as laptop-backup-2018
```
```
Scan root determines how paths are stored (mount prefix is stripped).
Use /mnt/disks/backup as scan root? [y/N]: y
```

If the user answers N, sift prompts for the root path:
```
Enter scan root: /mnt/disks/backup
```

With `--root` on the command line, no prompt:
```bash
sift scan /mnt/disks/backup --as laptop-backup-2018 --root /mnt/disks/backup
sift scan /mnt/disks/backup --as laptop-backup-2018 --root .
```

**Path transformation**: the root prefix is stripped and replaced with `/`.
`/mnt/disks/backup/Photos/vacation/IMG_001.jpg` becomes
`/Photos/vacation/IMG_001.jpg`. Files at the root become `/filename.jpg`.

**Validation**: the resolved scan path must start with the resolved root path.
Relative paths and `.` are resolved to absolute before use or display.

**Subdirectory scans**: scanning a subtree of the disk works — just specify the
full root:
```bash
sift scan /mnt/disks/backup/Photos --as laptop-backup-2018 --root /mnt/disks/backup
```

**Drive column**: virtual hosts store an empty drive value. The virtual host
itself represents the entire disk.

**Windows**: external drives mount as drive letters. `E:\` is the natural root:
```cmd
sift scan E:\ --as photo-pc-d-2013 --root E:\
```

### Host visibility (hide/unhide)

Any host — real or virtual — can be hidden from default views. Hidden hosts
are fully functional: scans still work, data is still queryable, aggregates
still refresh. The only effect is display filtering.

```bash
sift host hide laptop-backup-2018
sift host unhide laptop-backup-2018
```

**CLI behavior**:
- `sift ls`, `du`, `find`, `report`: skip hidden hosts by default
- `sift status`: skip hidden hosts by default; `sift status -v` includes them
- `--include-hidden`: includes hidden hosts in results
- `sift sets`: explicit host references work regardless of visibility
  (you name what you want)
- `sift host list`: always shows all hosts with their visibility status

**Frontend behavior**:
- Active (visible) hosts appear as host chips; "All" selects visible hosts only
- A muted "Hidden" chip appears to the right of "All"
- Clicking "Hidden" opens a dropdown with checkboxes for each hidden host
- Checking a hidden host adds it to the active view for the current session
- Session selections are not persisted — hidden hosts reset to hidden on
  page load (the point of hiding is "don't show by default"; use
  `sift host unhide` for permanent visibility changes)

### Host metadata (label, describe)

Any host can have a label and description for human context:

```bash
sift host label laptop-backup-2018 "Dell Latitude, pre-reformat"
sift host describe laptop-backup-2018 "WD 1TB USB drive, Brian's work laptop backup from Dec 2018"
```

With no value argument, the current value is displayed:
```bash
sift host label laptop-backup-2018
# → Dell Latitude, pre-reformat
```

**Labels** are short identifiers shown in the UI where space allows (tooltips,
`sift host list`, detail panels). They complement the slug-style host name
with human-readable context.

**Descriptions** are longer notes for the user's reference, shown in
`sift host list -v` or detail views.

## `sift host` Subcommand

```
sift host list                                  Show all hosts with status
sift host hide <name>                           Hide host from default views
sift host unhide <name>                         Restore host to default views
sift host label <name> [value]                  Set or show label
sift host describe <name> [value]               Set or show description
```

### `sift host list` output

```
NAME                      STATUS    LAST SCAN     FILES    LABEL
unraid                    visible   2h ago       412,831
brianmac                  visible   15m ago       87,204
laptop-backup-2018        hidden    2024-10-15     8,412   Dell Latitude, pre-reformat
photo-pc-d-2013           hidden    2024-11-02    23,107   WD 1TB from photo desktop
```

## Data Model

### `host_meta` table

```sql
CREATE TABLE IF NOT EXISTS host_meta (
    host TEXT PRIMARY KEY,
    hidden BOOLEAN DEFAULT FALSE,
    label TEXT,
    description TEXT,
    hidden_at TIMESTAMP
)
```

Hosts without a `host_meta` row default to `hidden=false, label=null,
description=null`. The table is tiny (one row per host) and effectively free
to query. No changes to the `files` table.

### API

Host metadata is served through the existing `/hosts` endpoint, which gains
`hidden`, `label`, and `description` fields from a `host_meta` LEFT JOIN.
Hosts without metadata rows return `hidden=false` with null label/description.

No new endpoints are required for reading. Host management mutations
(`hide`, `unhide`, `label`, `describe`) use:

```
PATCH /hosts/<name>    { "hidden": true/false, "label": "...", "description": "..." }
```

## Typical Workflows

### Scan and shelf an external drive

```bash
# Plug in the drive, scan it
sift scan /mnt/disks/backup --as laptop-backup-2018

# Add context for your future self
sift host label laptop-backup-2018 "Dell Latitude, pre-reformat"
sift host describe laptop-backup-2018 "WD 1TB USB, white label says 'BRIAN LAPTOP DEC 2018'"

# Check coverage
sift sets laptop-backup-2018:/ --covered --summary

# Shelf it — out of daily view
sift host hide laptop-backup-2018
```

### Quick coverage check later

```bash
# Don't need to unhide — sets works on any host by name
sift sets laptop-backup-2018:/ --covered --summary
```

### Find a file you forgot about

```bash
# Search across everything, including hidden hosts
sift find -name "thesis_final.docx" --include-hidden
```

### Temporarily browse in the UI

Click the "Hidden" chip → check "laptop-backup-2018" → browse the tree,
check dups, explore. Close the tab or reload — it's hidden again.

### Declutter a real host

```bash
# Grandma's PC scans weekly but you rarely look at it
sift host hide grandma-pc
```

Data keeps flowing. Scans keep running. Dups still compute. It's just not
in your face every day.

## Design Decisions

- **Host = any named source**: no separate concept for "virtual" vs "real"
  hosts in the data model. The distinction is purely about how the host was
  created (machine hostname vs `--as` flag) and is not stored.
- **`host_meta` table, not per-row flags**: visibility is a host-level concern.
  A tiny metadata table is cheaper and cleaner than adding a column to 800k+
  file rows.
- **`--root` mandatory with `--as`**: external disks mount at arbitrary paths.
  Stripping the mount prefix makes stored paths stable and meaningful.
  Interactive prompt avoids redundant CLI typing.
- **Session-scoped UI unhide**: peeking at hidden data shouldn't require a
  server mutation. Permanent visibility changes go through `sift host unhide`.
- **`sift sets` ignores visibility**: the primary use case for virtual hosts is
  coverage checking. Requiring unhide before `sift sets` would add friction
  to the core workflow.
- **No per-directory exclusion**: host-level hiding covers the offline-disk use
  case cleanly. Per-directory exclusion is a different feature with different
  complexity (dup counting implications, etc.) and is deferred.

## Interaction with Existing Features

- **`sift scan --as`**: creates the host identity. Subsequent scans with the
  same `--as` name update the same host's data. Re-scanning a disk that moved
  mount points works — old paths get tombstoned within the scanned root scope.
- **`sift sets`**: references virtual hosts by name (`laptop-backup-2018:/`).
  No visibility restrictions.
- **`sift status`**: shows visible hosts by default. `sift status -v` includes
  hidden hosts, marked as such.
- **`sift trim`**: works on hidden hosts. Useful for cleaning up a virtual host
  you no longer need without fully deleting it.
- **Duplicate computation**: hidden hosts are excluded from dup metrics by
  default (same as excluded from host chips). When a hidden host is
  session-selected in the UI, its files participate in dup computation for
  that view.
- **Aggregates**: `host_hash_stats` still refresh for hidden hosts after scans.
  Global `hash_stats` includes hidden host data in the background so that
  `sift sets --covered` remains accurate. Frontend dup metrics only include
  hosts in the current selection.
