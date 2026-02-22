"""CLI entry point — dispatches sift subcommands."""
import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sift",
        description="Distributed file inventory and deduplication",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # sift scan
    p_scan = sub.add_parser("scan", help="Scan a directory and send metadata to server")
    p_scan.add_argument("path", nargs="?", default="/", help="Path to scan (default: /)")
    p_scan.add_argument("--debug", action="store_true",
                        help="Fail immediately on any error; show excluded and skipped files")
    p_scan.add_argument("--ask", action="store_true",
                        help="Show what will be scanned and prompt for confirmation before starting")
    p_scan.add_argument("-x", "--one-filesystem", dest="one_filesystem", action="store_true",
                        help="Don't cross filesystem boundaries (skips mount points)")
    p_scan.add_argument("--quiet", action="store_true",
                        help="Suppress progress output (still prints final summary)")

    # sift ls
    p_ls = sub.add_parser("ls", help="List files/directories in the inventory",
                          conflict_handler="resolve")
    p_ls.add_argument("path", nargs="?", default=".", help="Path to list (default: .)")
    p_ls.add_argument("-l", dest="long", action="store_true", help="Long format")
    p_ls.add_argument("-h", dest="human", action="store_true", help="Human-readable sizes")
    p_ls.add_argument("-a", dest="all_files", action="store_true", help="Include hidden files")
    p_ls.add_argument("-S", dest="sort_size", action="store_true", help="Sort by size")
    p_ls.add_argument("-t", dest="sort_time", action="store_true", help="Sort by modification time")
    p_ls.add_argument("-r", dest="reverse", action="store_true", help="Reverse sort order")
    p_ls.add_argument("-1", dest="one_per_line", action="store_true", help="One entry per line")
    p_ls.add_argument("-R", dest="recursive", action="store_true", help="Recursive listing")
    p_ls.add_argument("--host", default=None, help="Host to query (default: local hostname)")
    p_ls.add_argument("--all-hosts", action="store_true", help="Show files from all hosts")
    p_ls.add_argument("--duplicates", action="store_true", help="Show only files with duplicates")
    p_ls.add_argument("--full-hash", dest="full_hash", action="store_true",
                      help="Show full SHA-256 hash instead of first 8 characters")

    # sift find
    p_find = sub.add_parser("find", help="Search the inventory")
    p_find.add_argument("path", nargs="?", default=".", help="Path prefix to search under")
    p_find.add_argument("-name", dest="name", default=None, help="Filename glob pattern")
    p_find.add_argument("-iname", dest="iname", default=None, help="Filename glob (case-insensitive)")
    p_find.add_argument("-size", dest="size", default=None, help="Size filter e.g. +1M -500k")
    p_find.add_argument("-mtime", dest="mtime", default=None, help="Mtime filter in days e.g. -7 +30")
    p_find.add_argument("--host", default=None, help="Host to query (default: local hostname)")
    p_find.add_argument("--all-hosts", action="store_true", help="Search files from all hosts")
    p_find.add_argument("-ext", dest="ext", default=None, help="Filter by extension")
    p_find.add_argument("-category", dest="category", default=None, help="Filter by category")
    p_find.add_argument("-duplicates", dest="duplicates", action="store_true",
                        help="Only show files with duplicates")
    p_find.add_argument("-hash", dest="hash", default=None, help="Match exact hash")
    p_find.add_argument("-ls", dest="ls", action="store_true",
                        help="List in long format (like ls -l)")

    # sift du
    p_du = sub.add_parser("du", help="Disk usage summary", conflict_handler="resolve")
    p_du.add_argument("path", nargs="?", default=".", help="Path to summarize")
    p_du.add_argument("-h", dest="human", action="store_true", help="Human-readable sizes")
    p_du.add_argument("-s", dest="summarize", action="store_true", help="Show only total")
    p_du.add_argument("-d", dest="depth", type=int, default=1, help="Max depth (default: 1)")
    p_du.add_argument("--sort", dest="sort", default="size", choices=["size", "name"],
                      help="Sort order (default: size)")
    p_du.add_argument("--host", default=None, help="Host to query (default: local hostname)")
    p_du.add_argument("--all-hosts", action="store_true", help="Show usage from all hosts")
    p_du.add_argument("--duplicates-only", dest="duplicates_only", action="store_true",
                      help="Only count duplicate files")
    p_du.add_argument("--by-category", dest="by_category", action="store_true",
                      help="Break down by file category")

    # sift server
    p_server = sub.add_parser("server", help="Start the sift server")
    p_server.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_server.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    p_server.add_argument("--db", default=None, help="Path to sift.duckdb")
    p_server.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")

    # sift status
    p_status = sub.add_parser("status", help="Show server and host status")
    p_status.add_argument("--host", default=None, help="Filter to a specific host")

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
        else:
            parser.print_help()
            sys.exit(1)
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        sys.exit(130)


if __name__ == "__main__":
    main()
