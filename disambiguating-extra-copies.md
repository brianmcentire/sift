# Tree Duplicate Semantics (Current)

This section is the current source of truth for duplicate-related labels and click behavior in Tree View.

## Terms

- **Duplicate hash**: a hash with more than one copy in the selected-host scope (respecting min dup size).
- **Subtree seed hash set** for directory `C`: duplicate hashes that have at least one member at `C` or below.
- **Scoped view**: results constrained to a subtree path.
- **Context view**: results across selected hosts, seeded by subtree membership.

## Directory row metric and label

- Display on directory rows: `X uniq dup hashes`.
- `X` means: number of distinct duplicate hashes in the subtree seed hash set for that row.
- This is presence/navigation information, not removable-copy math.

## Click actions in Tree View

Two adjacent controls intentionally do different jobs:

1. **Click `X uniq dup hashes` (text link) → Scoped duplicate-hash view**
   - Show results grouped by hash.
   - Include only duplicate hashes from selected hosts that have at least one member in clicked subtree.
   - Show only members at clicked subtree path or below.

2. **Click list icon (`☰`) → Context duplicate-hash view**
   - Start from the same subtree seed hash set.
   - Show results grouped by hash.
   - Include all members for those hashes across selected hosts (not path-filtered).
   - Highlight members inside clicked subtree (blue), so local relevance remains clear.

## Host scope and filtering rules

- Duplicate eligibility is always computed over selected hosts.
- `min dup size` is part of hash eligibility.
- Hashes are grouped/displayed by hash identity; member rows follow the selected action scope.

## UX guardrails

- Avoid copy labels on directory rows (`extra copies` is retired for directories).
- Keep semantics stable even when selected hosts include machines that do not contain that path.
- Host badges on directory rows should represent path presence and avoid implying path existence where none exists.

---

#deprecated

# Only-Dups Tree Filter: Navigation and Labeling Semantics

This document captures the finalized UX semantics for the "Only dups" tree filter and associated labels, superseding prior drafts.

---

## 1. Core Principle: Navigation vs. Redundancy

We separate the purpose of directories (navigation) from files (redundancy).

- **Only dups filter**: "Show me branches that lead to duplicate sets."
- **Directory Label**: "Tell me how many distinct duplicate sets live down this path."
- **File Label**: "Tell me how many redundant copies of this file exist."

---

## 2. Directory Semantics (The "PMS" Problem Solved)

### Visibility (Only dups ON)
A directory is visible if it contains **at least one file that is a member of a duplicate set** (under current host/size filters).

- **Rule:** `(dup_count > 0) OR (cross_host_match AND selected_hosts_match)`
- **Key change:** Do NOT use `extraCopies` (intra-subtree redundancy) for visibility. A directory with `1 unique dup set` but `0 extra copies` (e.g. PMS folder with one file duplicated elsewhere) MUST be visible.

### Label (Hash Column)
- **Display:** `X uniq dup sets`
- **Source:** `dup_hash_count` (already returned by `/tree/dup-metrics`)
- **Meaning:** "This subtree contains files belonging to X distinct duplicate sets."
- **Why:** Stable indicator of duplicate content presence, regardless of whether the redundancy is internal to this folder or external.

---

## 3. File Semantics

### Visibility (Only dups ON)
A file is visible if it is a member of a duplicate set.

- **Rule:** `(dup_count > 0) OR (cross_host_match AND selected_hosts_match)`

### Label (Hash Column)
- **Display:** `Y extra copies`
- **Meaning:** "This specific file has Y redundant copies elsewhere in the current scope."
- **Source:** `dup_count - 1` (or derived from cross-host count if multi-host selected)

---

## 4. Implementation Plan

### Frontend (`frontend/src/components/FileRow.jsx`)
- Change directory hash cell renderer:
  - **Old:** `extraCopies` (derived) + label "extra copies"
  - **New:** `entry.dup_hash_count` + label "uniq dup sets"
- Keep file hash cell renderer as-is ("extra copies").

### Frontend (`frontend/src/App.jsx`)
- Ensure `Only dups` tree filtering logic uses duplicate membership (`dup_count > 0`), NOT `extraCopies`. (This aligns with the navigation-safety fix already applied).

### Backend (`server/main.py`)
- No changes required. `dup_hash_count` is already efficient and present in tree payloads.

---

## 5. Deprecated / Dismissed Concepts

### [Dismissed] "Removable Copies" (Server-Side Metric)
*Reason:* Too heavy to compute on the fly; adds backend complexity for marginal UX gain. The distinction between "uniq dup sets" (dirs) and "extra copies" (files) solves the user confusion without new DB queries.

### [Dismissed] "Extra Copies" on Directories
*Reason:* Confusing. Users interpreted "0 extra copies" as "no duplicates here," hiding valid navigation paths like the PMS example. Replaced by "uniq dup sets."
