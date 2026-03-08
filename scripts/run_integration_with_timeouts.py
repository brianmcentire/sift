#!/usr/bin/env python3
"""Run integration tests one-by-one with per-test timeout.

Example:
  python scripts/run_integration_with_timeouts.py --server 127.0.0.1
  python scripts/run_integration_with_timeouts.py --server sift.local --port 9000
  python scripts/run_integration_with_timeouts.py --server http://192.168.1.200:8765
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class TestResult:
    nodeid: str
    status: str
    seconds: float


def _normalize_server(raw: str, port: int) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Server value is empty")

    # If the caller already passed a URL, use it as-is.
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        if not parsed.hostname:
            raise ValueError(f"Invalid server URL: {raw}")
        return raw.rstrip("/")

    # Otherwise treat as host/ip and normalize.
    return f"http://{raw}:{port}"


def _collect_nodeids(
    repo_root: Path, env: dict[str, str], keyword: str | None
) -> list[str]:
    cmd = ["pytest", "-m", "integration", "--collect-only", "-q"]
    if keyword:
        cmd.extend(["-k", keyword])
    proc = subprocess.run(cmd, cwd=repo_root, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        print("Failed collecting integration tests", file=sys.stderr)
        if proc.stdout:
            print(proc.stdout, file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)

    nodeids: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("tests/") and "::" in line:
            nodeids.append(line)
    return nodeids


def _run_single(
    repo_root: Path,
    env: dict[str, str],
    nodeid: str,
    timeout_seconds: int,
    extra_pytest_args: list[str],
) -> TestResult:
    cmd = ["pytest", "-q", "-m", "integration", nodeid, *extra_pytest_args]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        elapsed = time.time() - start
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode == 0:
            status = "PASS"
        elif "skipped" in output.lower():
            status = "SKIP"
        else:
            status = "FAIL"

        print(f"{status} in {elapsed:.1f}s")
        if status == "FAIL":
            print("--- failure output (last 80 lines) ---")
            lines = output.splitlines()
            for line in lines[-80:]:
                print(line)

        return TestResult(nodeid=nodeid, status=status, seconds=elapsed)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - start
        print(f"TIMEOUT (> {timeout_seconds}s): {nodeid}")
        stdout_tail = ""
        stderr_tail = ""
        if exc.stdout:
            stdout_tail = (
                exc.stdout
                if isinstance(exc.stdout, str)
                else exc.stdout.decode(errors="ignore")
            )
        if exc.stderr:
            stderr_tail = (
                exc.stderr
                if isinstance(exc.stderr, str)
                else exc.stderr.decode(errors="ignore")
            )
        if stdout_tail:
            print("--- partial stdout (tail) ---")
            print(stdout_tail[-4000:])
        if stderr_tail:
            print("--- partial stderr (tail) ---")
            print(stderr_tail[-4000:])
        return TestResult(nodeid=nodeid, status="TIMEOUT", seconds=elapsed)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run integration tests one-by-one with timeout and explicit server target."
    )
    parser.add_argument(
        "--server",
        required=True,
        help="Server hostname/IP or full URL (e.g. 127.0.0.1, sift.local, http://192.168.1.200:8765)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port used when --server is hostname/IP only (default: 8765)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Per-test timeout in seconds (default: 900 = 15 minutes)",
    )
    parser.add_argument(
        "--keyword",
        default=None,
        help="Optional pytest -k expression to run a subset",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Collect and print matching integration test node IDs only",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra pytest args (prepend with --, e.g. -- -x)",
    )
    args = parser.parse_args()

    try:
        server_url = _normalize_server(args.server, args.port)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["SIFT_TEST_SERVER"] = server_url

    print(f"Target server: {server_url}")
    print(f"Per-test timeout: {args.timeout}s")

    nodeids = _collect_nodeids(repo_root, env, args.keyword)
    print(f"Collected {len(nodeids)} integration tests")
    if not nodeids:
        return 0

    if args.collect_only:
        for nodeid in nodeids:
            print(nodeid)
        return 0

    extra_pytest_args = [a for a in args.pytest_args if a != "--"]

    results: list[TestResult] = []
    suite_start = time.time()
    for idx, nodeid in enumerate(nodeids, start=1):
        print(f"\n[{idx}/{len(nodeids)}] RUN {nodeid}")
        results.append(
            _run_single(
                repo_root=repo_root,
                env=env,
                nodeid=nodeid,
                timeout_seconds=args.timeout,
                extra_pytest_args=extra_pytest_args,
            )
        )

    elapsed = time.time() - suite_start
    print("\n=== SUMMARY ===")
    for r in results:
        print(f"{r.status:8} {r.seconds:7.1f}s  {r.nodeid}")
    print(f"Total elapsed: {elapsed:.1f}s")

    timeouts = [r for r in results if r.status == "TIMEOUT"]
    fails = [r for r in results if r.status == "FAIL"]
    if timeouts:
        print("\nTimed out tests:")
        for r in timeouts:
            print(f"- {r.nodeid}")
    if fails:
        print("\nFailed tests:")
        for r in fails:
            print(f"- {r.nodeid}")

    if timeouts:
        return 2
    if fails:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
