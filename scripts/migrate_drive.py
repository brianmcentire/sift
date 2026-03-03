#!/usr/bin/env python3
"""One-time migration: fix Windows drive-letter paths from old format to new.

Old format: drive='',  path='d:/users/file.txt',  path_display='D:/Users/file.txt'
New format: drive='D', path='/users/file.txt',     path_display='/Users/file.txt'

Usage:
    python3 scripts/migrate_drive.py --db ~/.sift.duckdb --host photoshop-pc --drive D
    python3 scripts/migrate_drive.py --db ~/.sift.duckdb --host photoshop-pc --drive D --execute
"""

import argparse
import sys

import duckdb


def main():
    parser = argparse.ArgumentParser(description="Migrate old-format Windows drive paths in sift DB")
    parser.add_argument("--db", required=True, help="Path to sift.duckdb file")
    parser.add_argument("--host", required=True, help="Hostname to migrate (e.g. photoshop-pc)")
    parser.add_argument("--drive", required=True, help="Drive letter (e.g. D)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually write changes (default is dry-run)")
    args = parser.parse_args()

    drive = args.drive.upper()
    if len(drive) != 1 or not drive.isalpha():
        print(f"ERROR: --drive must be a single letter, got '{args.drive}'")
        sys.exit(1)

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"=== Drive Path Migration ({mode}) ===")
    print(f"DB:    {args.db}")
    print(f"Host:  {args.host}")
    print(f"Drive: {drive}")
    print()

    try:
        conn = duckdb.connect(args.db)
    except Exception as e:
        print(f"ERROR: Could not open database: {e}")
        print("Make sure the sift server is stopped (DuckDB is single-writer).")
        sys.exit(1)

    # --- Diagnostic: current state ---
    print("--- Current state ---")
    rows = conn.execute(
        "SELECT drive, COUNT(*) as cnt, MIN(path), MAX(path) "
        "FROM files WHERE host = ? GROUP BY drive ORDER BY drive",
        [args.host],
    ).fetchall()
    if not rows:
        print(f"No files found for host '{args.host}'. Nothing to do.")
        conn.close()
        return
    for drive_val, cnt, min_path, max_path in rows:
        label = repr(drive_val) if drive_val else "''"
        print(f"  drive={label:>4}  count={cnt:>8}  min_path={min_path}")
        print(f"{'':>30}  max_path={max_path}")
    print()

    # --- Count old-format rows ---
    old_pattern = "_:/%"  # single char + colon + slash
    (old_count,) = conn.execute(
        "SELECT COUNT(*) FROM files WHERE host = ? AND drive = '' AND path LIKE ?",
        [args.host, old_pattern],
    ).fetchone()
    print(f"Old-format rows (drive='', path like 'x:/...'): {old_count}")

    if old_count == 0:
        print("Nothing to migrate.")
        conn.close()
        return

    # --- Count conflicts (old rows whose migrated key already exists as new-format) ---
    (conflict_count,) = conn.execute(
        """
        SELECT COUNT(*) FROM files AS old
        WHERE old.host = ? AND old.drive = '' AND old.path LIKE ?
          AND EXISTS (
            SELECT 1 FROM files AS new
            WHERE new.host = old.host
              AND new.drive = UPPER(LEFT(old.path, 1))
              AND new.path = SUBSTR(old.path, 3)
          )
        """,
        [args.host, old_pattern],
    ).fetchone()
    migrate_count = old_count - conflict_count

    print(f"  Conflicts (new-format row already exists): {conflict_count}")
    print(f"  Non-conflicting (will be migrated):        {migrate_count}")
    print()

    if not args.execute:
        print("DRY-RUN complete. Pass --execute to apply changes.")
        conn.close()
        return

    # --- Execute migration ---
    print("Migrating non-conflicting rows...")
    migrated = conn.execute(
        """
        UPDATE files
        SET drive = UPPER(LEFT(path, 1)),
            path = SUBSTR(path, 3),
            path_display = SUBSTR(path_display, 3)
        WHERE host = ? AND drive = '' AND path LIKE ?
          AND NOT EXISTS (
            SELECT 1 FROM files AS new
            WHERE new.host = files.host
              AND new.drive = UPPER(LEFT(files.path, 1))
              AND new.path = SUBSTR(files.path, 3)
          )
        """,
        [args.host, old_pattern],
    ).fetchone()
    # DuckDB UPDATE returns row count via rowcount or we can re-query
    print(f"  Updated: {migrate_count} rows")

    if conflict_count > 0:
        print(f"Deleting {conflict_count} stale conflicting rows...")
        conn.execute(
            """
            DELETE FROM files
            WHERE host = ? AND drive = '' AND path LIKE ?
              AND EXISTS (
                SELECT 1 FROM files AS new
                WHERE new.host = files.host
                  AND new.drive = UPPER(LEFT(files.path, 1))
                  AND new.path = SUBSTR(files.path, 3)
              )
            """,
            [args.host, old_pattern],
        )
        print(f"  Deleted: {conflict_count} rows")

    print()

    # --- Verify ---
    print("--- Post-migration state ---")
    rows = conn.execute(
        "SELECT drive, COUNT(*) as cnt, MIN(path), MAX(path) "
        "FROM files WHERE host = ? GROUP BY drive ORDER BY drive",
        [args.host],
    ).fetchall()
    for drive_val, cnt, min_path, max_path in rows:
        label = repr(drive_val) if drive_val else "''"
        print(f"  drive={label:>4}  count={cnt:>8}  min_path={min_path}")
        print(f"{'':>30}  max_path={max_path}")

    # Check for any remaining old-format
    (remaining,) = conn.execute(
        "SELECT COUNT(*) FROM files WHERE host = ? AND drive = '' AND path LIKE ?",
        [args.host, old_pattern],
    ).fetchone()
    if remaining > 0:
        print(f"\nWARNING: {remaining} old-format rows still remain!")
    else:
        print("\nAll old-format rows migrated successfully.")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
