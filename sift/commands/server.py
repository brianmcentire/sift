"""sift server — start the FastAPI server with uvicorn."""
from __future__ import annotations

import os
import sys


def cmd_server(args) -> None:
    try:
        import uvicorn
    except ImportError:
        print("sift: uvicorn not installed. Run: pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)

    host_bind = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8765)
    reload = getattr(args, "reload", False)
    db_path = getattr(args, "db", None)

    if db_path:
        os.environ["SIFT_DB_PATH"] = db_path

    print(f"Starting sift server on {host_bind}:{port}", flush=True)

    uvicorn.run(
        "server.main:app",
        host=host_bind,
        port=port,
        reload=reload,
    )
