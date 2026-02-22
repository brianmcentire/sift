"""SHA-256 hashing and rehash cache logic."""
from __future__ import annotations

import hashlib
import math
import os
from typing import Optional


_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB default


def hash_file(path: str, chunk_size: int = _CHUNK_SIZE) -> Optional[str]:
    """
    Compute SHA-256 hex digest of a file.
    Returns None on PermissionError or OSError (caller should log).
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except PermissionError:
        return None
    except OSError:
        return None


def needs_rehash(
    stat_result: os.stat_result,
    cached: Optional[dict],
) -> bool:
    """
    Return True if the file needs to be (re)hashed.
    cached is a dict with keys 'mtime' and 'size_bytes', or None if not cached.
    """
    if cached is None:
        return True
    cached_mtime = cached.get("mtime")
    cached_size = cached.get("size_bytes")
    current_mtime = math.floor(stat_result.st_mtime)
    current_size = stat_result.st_size
    # If mtime or size changed, rehash
    if cached_mtime is None or cached_size is None:
        return True
    return current_mtime != cached_mtime or current_size != cached_size
