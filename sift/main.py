"""CLI entry point — dispatches sift subcommands."""

import argparse
import re
import sys


def main() -> None:
    from sift.commands import get_version

    parser = argparse.ArgumentParser(
        prog="sift",
        description="Distributed file inventory and deduplication",
    )
    parser.add_argument("--version", action="version", version=f"sift {get_version()}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # sift scan
    p_scan = sub.add_parser("scan", help="Scan a directory and send metadata to server")
    p_scan.add_argument(
        "path", nargs="?", default=".", help="Path to scan (default: current directory)"
    )
    p_scan.add_argument(
        "--debug",
        action="store_true",
        help="Fail immediately on any error; show excluded and skipped files",
    )
    p_scan.add_argument(
        "--ask",
        action="store_true",
        help="Show what will be scanned and prompt for confirmation before starting",
    )
    p_scan.add_argument(
        "-x",
        "--one-filesystem",
        dest="one_filesystem",
        action="store_true",
        help="Don't cross filesystem boundaries (skips mount points)",
    )
    p_scan.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output (still prints final summary)",
    )
    p_scan.add_argument(
        "--null-hash-retry",
        action="store_true",
        help="Retry hashing unchanged files that currently have null hash in datastore",
    )
    p_scan.add_argument("--yolo", action="store_true", help=argparse.SUPPRESS)
    p_scan.add_argument(
        "--as", dest="as_host", default=None,
        help="Scan as a named virtual host (e.g. laptop-backup-2018)",
    )
    p_scan.add_argument(
        "--root", default=None,
        help="Scan root prefix to strip from stored paths (required with --as)",
    )
    p_scan.add_argument(
        "--keep-deleted",
        dest="keep_deleted",
        action="store_true",
        help="Skip auto-trim of deleted files after scan completes",
    )

    # sift ls
    p_ls = sub.add_parser(
        "ls", help="List files/directories in the inventory", conflict_handler="resolve"
    )
    p_ls.add_argument("path", nargs="?", default=".", help="Path to list (default: .)")
    p_ls.add_argument("-l", dest="long", action="store_true", help="Long format")
    p_ls.add_argument(
        "-h", dest="human", action="store_true", help="Human-readable sizes"
    )
    p_ls.add_argument(
        "-a", dest="all_files", action="store_true", help="Include hidden files"
    )
    p_ls.add_argument("-S", dest="sort_size", action="store_true", help="Sort by size")
    p_ls.add_argument(
        "-t", dest="sort_time", action="store_true", help="Sort by modification time"
    )
    p_ls.add_argument(
        "-r", dest="reverse", action="store_true", help="Reverse sort order"
    )
    p_ls.add_argument(
        "-1", dest="one_per_line", action="store_true", help="One entry per line"
    )
    p_ls.add_argument(
        "-R", dest="recursive", action="store_true", help="Recursive listing"
    )
    p_ls.add_argument(
        "--host", default=None, help="Host to query (default: local hostname)"
    )
    p_ls.add_argument(
        "--all-hosts", action="store_true", help="Show files from all hosts"
    )
    p_ls.add_argument(
        "--duplicates", action="store_true", help="Show only files with duplicates"
    )
    p_ls.add_argument(
        "--include-hidden", action="store_true",
        help="Include hidden hosts in results",
    )
    p_ls.add_argument(
        "--full-hash",
        dest="full_hash",
        action="store_true",
        help="Show full SHA-256 hash instead of first 8 characters",
    )

    # sift find
    p_find = sub.add_parser("find", help="Search the inventory")
    p_find.add_argument(
        "path", nargs="?", default=".", help="Path prefix to search under"
    )
    p_find.add_argument(
        "-name", dest="name", default=None, help="Filename glob pattern"
    )
    p_find.add_argument(
        "-iname", dest="iname", default=None, help="Filename glob (case-insensitive)"
    )
    p_find.add_argument(
        "-size", dest="size", default=None, help="Size filter e.g. +1M -500k"
    )
    p_find.add_argument(
        "-mtime", dest="mtime", default=None, help="Mtime filter in days e.g. -7 +30"
    )
    p_find.add_argument(
        "--host", default=None, help="Host to query (default: local hostname)"
    )
    p_find.add_argument(
        "--all-hosts", action="store_true", help="Search files from all hosts"
    )
    p_find.add_argument("-ext", dest="ext", default=None, help="Filter by extension")
    p_find.add_argument(
        "-category", dest="category", default=None, help="Filter by category"
    )
    p_find.add_argument(
        "-duplicates",
        dest="duplicates",
        action="store_true",
        help="Only show files with duplicates",
    )
    p_find.add_argument("-hash", dest="hash", default=None, help="Match exact hash")
    p_find.add_argument(
        "-ls", dest="ls", action="store_true", help="List in long format (like ls -l)"
    )
    p_find.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=2000,
        help="Maximum results to return (default: 2000)",
    )
    p_find.add_argument(
        "--lite",
        dest="lite",
        action="store_true",
        help="Skip cross-host enrichment for faster searches (default behavior)",
    )
    p_find.add_argument(
        "--with-other-hosts",
        dest="with_other_hosts",
        action="store_true",
        help="Include cross-host enrichment in results (slower on very large datasets)",
    )
    p_find.add_argument(
        "--include-hidden", action="store_true",
        help="Include hidden hosts in results",
    )

    # sift du
    p_du = sub.add_parser("du", help="Disk usage summary", conflict_handler="resolve")
    p_du.add_argument("path", nargs="?", default=".", help="Path to summarize")
    p_du.add_argument(
        "-h", dest="human", action="store_true", help="Human-readable sizes"
    )
    p_du.add_argument(
        "-s", dest="summarize", action="store_true", help="Show only total"
    )
    p_du.add_argument(
        "-d", dest="depth", type=int, default=1, help="Max depth (default: 1)"
    )
    p_du.add_argument(
        "--sort",
        dest="sort",
        default="size",
        choices=["size", "name"],
        help="Sort order (default: size)",
    )
    p_du.add_argument(
        "--host", default=None, help="Host to query (default: local hostname)"
    )
    p_du.add_argument(
        "--all-hosts", action="store_true", help="Show usage from all hosts"
    )
    p_du.add_argument(
        "--duplicates-only",
        dest="duplicates_only",
        action="store_true",
        help="Only count duplicate files",
    )
    p_du.add_argument(
        "--by-category",
        dest="by_category",
        action="store_true",
        help="Break down by file category",
    )
    p_du.add_argument(
        "--include-hidden", action="store_true",
        help="Include hidden hosts in results",
    )

    # sift server
    p_server = sub.add_parser("server", help="Start the sift server")
    p_server.add_argument(
        "--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)"
    )
    p_server.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    p_server.add_argument("--db", default=None, help="Path to sift.duckdb")
    p_server.add_argument(
        "--reload", action="store_true", help="Enable auto-reload (dev only)"
    )

    # sift status
    p_status = sub.add_parser("status", help="Show server and host status")
    p_status.add_argument("--host", default=None, help="Filter to a specific host")
    p_status.add_argument(
        "-v", "--verbose", action="store_true", help="Show recent scan history"
    )
    p_status.add_argument(
        "--stats", action="store_true", help="Include dup stats (slower)"
    )
    p_status.add_argument(
        "--showroots",
        action="store_true",
        help="Show effective complete scan roots per host",
    )

    # sift trim
    p_trim = sub.add_parser("trim", help="Remove inventory rows from the datastore")
    p_trim.add_argument(
        "targets",
        nargs="*",
        help="Optional path plus optional basename patterns (* and ?)",
    )
    p_trim.add_argument(
        "--path",
        default=None,
        help="Explicit path to trim under (alternative to positional path)",
    )
    p_trim.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Trim recursively under path (default: current directory only)",
    )
    trim_mode = p_trim.add_mutually_exclusive_group()
    trim_mode.add_argument(
        "--deleted",
        action="store_true",
        help="Only trim stale tombstoned rows (requires covering complete scans). If no path is provided, defaults to -r /",
    )
    trim_mode.add_argument(
        "--unsafe-delete-not-seen-since",
        dest="unsafe_delete_not_seen_since",
        default=None,
        help="Unsafe: trim rows with last_seen_at before YYYYMMDD, or use 'latest' per complete root scan date",
    )
    p_trim.add_argument(
        "--host",
        default=None,
        help="Target host (default: local hostname)",
    )
    p_trim.add_argument(
        "--batch-size",
        dest="batch_size",
        type=int,
        default=5000,
        help="Rows deleted per request (default: 5000)",
    )
    p_trim.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress live progress output",
    )
    p_trim.add_argument(
        "--debug",
        action="store_true",
        help="Show detailed trim progress and decisions",
    )
    p_trim.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be trimmed without deleting",
    )
    p_trim.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="With --dry-run, list matching paths",
    )

    # sift locate
    p_locate = sub.add_parser("locate", help="Search the inventory by filename pattern")
    p_locate.add_argument("pattern", help="Glob pattern, e.g. '*.mp4'")
    p_locate.add_argument(
        "-i", dest="case_insensitive", action="store_true",
        help="Case-insensitive matching",
    )
    p_locate.add_argument(
        "--host", default=None, help="Host to query (default: local hostname)",
    )
    p_locate.add_argument(
        "--all-hosts", action="store_true", help="Search all hosts",
    )
    p_locate.add_argument(
        "--limit", type=int, default=1000, help="Max results (default: 1000, 0 = unlimited)",
    )
    p_locate.add_argument(
        "-a", "--all", dest="all_results", action="store_true",
        help="Shorthand for --limit 0",
    )
    p_locate.add_argument(
        "-l", dest="long", action="store_true", help="Long format: size, date, path",
    )
    p_locate.add_argument(
        "-c", "--count", dest="count", action="store_true",
        help="Print match count only",
    )
    p_locate.add_argument(
        "--include-hidden", action="store_true",
        help="Include hidden hosts in results",
    )

    # sift diff
    p_diff = sub.add_parser("diff", help="Compare two directories in the inventory")
    p_diff.add_argument("dir1", help="First directory or host:/path")
    p_diff.add_argument("dir2", help="Second directory or host:/path")
    p_diff.add_argument(
        "-r", dest="recursive", action="store_true", help="Recursive comparison",
    )

    # sift comm
    p_comm = sub.add_parser(
        "comm", help="Compare two directories, three-column output",
        conflict_handler="resolve",
    )
    p_comm.add_argument("dir1", help="First directory or host:/path")
    p_comm.add_argument("dir2", help="Second directory or host:/path")
    p_comm.add_argument(
        "-r", dest="recursive", action="store_true", help="Recursive comparison",
    )
    p_comm.add_argument(
        "--depth", type=int, default=None,
        help="Max depth (1 = immediate contents)",
    )
    p_comm.add_argument(
        "--hashes", action="store_true",
        help="Compare by sorted hashes instead of filenames",
    )
    p_comm.add_argument(
        "-1", dest="suppress_1", action="store_true",
        help="Suppress column 1 (only-in-dir1)",
    )
    p_comm.add_argument(
        "-2", dest="suppress_2", action="store_true",
        help="Suppress column 2 (only-in-dir2)",
    )
    p_comm.add_argument(
        "-3", dest="suppress_3", action="store_true",
        help="Suppress column 3 (common files)",
    )
    p_comm.add_argument(
        "--yes", "-y", action="store_true",
        help="Suppress large-output warning",
    )
    p_comm.add_argument(
        "-h", "--human", dest="human", action="store_true",
        help="Human-readable sizes",
    )

    # sift sets
    p_sets = sub.add_parser(
        "sets", help="Hash-based set operations between directories",
    )
    p_sets.add_argument(
        "paths", nargs="*",
        help="Paths: first = source (A), rest = targets (B)",
    )
    p_sets.add_argument(
        "-a", dest="a_paths", nargs="+", metavar="PATH",
        help="Explicit source paths (set A)",
    )
    p_sets.add_argument(
        "-b", dest="b_paths", nargs="+", metavar="PATH",
        help="Explicit target paths (set B)",
    )
    p_sets.add_argument(
        "--covered", nargs="*", metavar="HOST", default=None,
        help="B = all hashes in datastore (optionally limited to specified hosts)",
    )
    p_sets.add_argument(
        "--min-size", default=None,
        help="Ignore files below threshold (e.g., 1M, 500k)",
    )
    p_sets.add_argument(
        "-n", type=int, default=None, metavar="N",
        help="Limit file list output to N entries",
    )
    p_sets.add_argument(
        "--summary", action="store_true",
        help="Summary only, no file list",
    )
    p_sets.add_argument(
        "--no-summary", action="store_true",
        help="Suppress summary (file list only)",
    )
    p_sets.add_argument(
        "-l", "--long", dest="long", action="store_true",
        help="Show size and date in file list",
    )
    p_sets.add_argument(
        "--reverse", action="store_true",
        help="Show B-A instead of A-B",
    )
    p_sets.add_argument(
        "--common", action="store_true",
        help="Show A∩B (intersection)",
    )
    p_sets.add_argument(
        "--json", action="store_true",
        help="JSON output to stdout",
    )

    # sift organize
    p_organize = sub.add_parser(
        "organize",
        help="Generate a script to reorganize donor files to match a model host's structure",
        usage="sift organize model target --from PATH [--from PATH ...] [--move | --copy | --sift-mv]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Generate a shell script that rearranges files from local donor directories\n"
        "to match the directory structure of a model host in the sift datastore.\n"
        "\n"
        "The script is written to stdout — redirect to a file, review, then run it.\n"
        "Files already in the target at the correct path are skipped (\"already in place\").\n"
        "Files in the target that aren't in the model are left untouched.\n"
        "\n"
        "Examples:\n"
        "  # Pre-seed a mirror of a Windows PC from existing Unraid backups:\n"
        "  sift organize Photoshop-PC:D:\\ /mnt/user/mirrors/photoshop-d \\\n"
        "    --from /mnt/user/backups --from /mnt/user/media/photos > organize.sh\n"
        "\n"
        "  # Same, but copy instead of move (leaves donors intact):\n"
        "  sift organize Photoshop-PC:D:\\ /mnt/user/mirrors/photoshop-d \\\n"
        "    --from /mnt/user/backups --copy > organize.sh\n"
        "\n"
        "  # Review the script, then run it:\n"
        "  less organize.sh\n"
        "  bash organize.sh",
    )
    p_organize.add_argument(
        "model", help="Model host:path whose structure to replicate (e.g. MyPC:D:\\)",
    )
    p_organize.add_argument(
        "target", help="Local target directory where organized structure will be built",
    )
    p_organize.add_argument(
        "--from", dest="donors", action="append", required=True, metavar="PATH",
        help="Donor directory on local host (repeatable, first = highest priority)",
    )
    organize_mode = p_organize.add_mutually_exclusive_group()
    organize_mode.add_argument(
        "--move", dest="mode", action="store_const", const="move", default="move",
        help="Use mv for file operations (default)",
    )
    organize_mode.add_argument(
        "--copy", dest="mode", action="store_const", const="copy",
        help="Use cp instead of mv",
    )
    organize_mode.add_argument(
        "--sift-mv", dest="mode", action="store_const", const="sift-mv",
        help="Like --move but uses 'sift mv' to update the datastore in one step",
    )

    # sift mv
    p_mv = sub.add_parser(
        "mv",
        help="Move files and update the sift datastore",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Move files on disk and update their paths in the sift datastore,\n"
        "avoiding a full rescan. Like mv but sift-aware.\n"
        "\n"
        "Examples:\n"
        "  sift mv ~/old-photos ~/media/photos\n"
        "  sift mv file1.txt file2.txt /dest/dir/\n"
        "  sift mv --db-only /old/path /new/path\n"
        "  sift mv --dry-run ~/dir1 ~/dir2",
    )
    p_mv.add_argument(
        "paths", nargs="+",
        help="Source(s) and destination (last argument)",
    )
    p_mv.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without making changes",
    )
    p_mv.add_argument(
        "--db-only", action="store_true",
        help="Update datastore only, skip filesystem move",
    )
    p_mv.add_argument(
        "--force", action="store_true",
        help="Overwrite if destination already exists in datastore",
    )

    # sift host
    p_host = sub.add_parser("host", help="Manage host visibility and metadata")
    host_sub = p_host.add_subparsers(dest="host_action", metavar="ACTION")

    p_host_list = host_sub.add_parser("list", help="Show all hosts with status")
    p_host_list.add_argument("-v", "--verbose", action="store_true", help="Show descriptions")

    p_hide = host_sub.add_parser("hide", help="Hide host from default views")
    p_hide.add_argument("name", help="Host name")

    p_unhide = host_sub.add_parser("unhide", help="Restore host to default views")
    p_unhide.add_argument("name", help="Host name")

    p_label = host_sub.add_parser("label", help="Set or show host label")
    p_label.add_argument("name", help="Host name")
    p_label.add_argument("value", nargs="?", default=None, help="Label text (omit to show)")

    p_describe = host_sub.add_parser("describe", help="Set or show host description")
    p_describe.add_argument("name", help="Host name")
    p_describe.add_argument("value", nargs="?", default=None, help="Description (omit to show)")

    # sift report
    p_report = sub.add_parser("report", help="Show datastore report across all hosts")
    p_report.add_argument(
        "--include-hidden", action="store_true",
        help="Include hidden hosts in results",
    )

    # sift config
    sub.add_parser("config", help="Configure the sift server URL")

    # sift upgrade
    sub.add_parser("upgrade", help="Upgrade sift to the latest version from GitHub")

    # Preprocess -NUMBER shorthand for 'sift sets' (e.g., -10 → -n 10)
    _argv = sys.argv[1:]
    if _argv and _argv[0] == "sets":
        for _i in range(1, len(_argv)):
            if re.match(r"^-\d+$", _argv[_i]):
                _argv[_i : _i + 1] = ["-n", _argv[_i][1:]]
                break
        args = parser.parse_args(_argv)
    else:
        args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "scan":
            from sift.commands.scan import cmd_scan

            cmd_scan(args)
        elif args.command == "ls":
            from sift.commands.ls import cmd_ls

            cmd_ls(args)
        elif args.command == "find":
            from sift.commands.find import cmd_find

            cmd_find(args)
        elif args.command == "du":
            from sift.commands.du import cmd_du

            cmd_du(args)
        elif args.command == "server":
            from sift.commands.server import cmd_server

            cmd_server(args)
        elif args.command == "status":
            from sift.commands.status import cmd_status

            cmd_status(args)
        elif args.command == "trim":
            from sift.commands.trim import cmd_trim

            cmd_trim(args)
        elif args.command == "host":
            from sift.commands.host import cmd_host

            cmd_host(args)
        elif args.command == "report":
            from sift.commands.report import cmd_report

            cmd_report(args)
        elif args.command == "config":
            from sift.commands.config import cmd_config

            cmd_config(args)
        elif args.command == "upgrade":
            from sift.commands.upgrade import cmd_upgrade

            cmd_upgrade(args)
        elif args.command == "locate":
            from sift.commands.locate import cmd_locate

            cmd_locate(args)
        elif args.command == "diff":
            from sift.commands.diff import cmd_diff

            cmd_diff(args)
        elif args.command == "comm":
            from sift.commands.comm import cmd_comm

            cmd_comm(args)
        elif args.command == "sets":
            from sift.commands.sets import cmd_sets

            cmd_sets(args)
        elif args.command == "organize":
            from sift.commands.organize import cmd_organize

            cmd_organize(args)
        elif args.command == "mv":
            from sift.commands.mv import cmd_mv

            cmd_mv(args)
        else:
            parser.print_help()
            sys.exit(1)
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        sys.exit(130)


if __name__ == "__main__":
    main()
