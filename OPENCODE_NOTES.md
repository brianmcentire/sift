# OpenCode Notes

- Quiet mode follow-up: in `sift/commands/scan.py` (post-`a8a83ff`), `_flush_queued_seen()` is invoked from the heartbeat loop, but the loop short-circuits on `if quiet: continue`. This may prevent incremental `/files/seen` flushes during `sift scan --quiet`, causing larger end-of-scan tail latency again. Revisit and ensure seen flush scheduling still runs in quiet mode (while keeping UI/progress output suppressed).
