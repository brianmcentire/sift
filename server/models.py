"""Pydantic request/response models for the sift server API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Ingest models
# ---------------------------------------------------------------------------

class FileRecord(BaseModel):
    host: str
    drive: str = ""
    path: str
    path_display: str
    filename: str
    ext: str = ""
    file_category: str = "other"
    size_bytes: Optional[int] = None
    hash: Optional[str] = None
    mtime: Optional[int] = None
    last_checked: datetime
    source_os: str
    skipped_reason: Optional[str] = None
    last_seen_at: datetime


class SeenEntry(BaseModel):
    drive: str = ""
    path: str


class SeenRequest(BaseModel):
    host: str
    last_seen_at: datetime
    paths: list[SeenEntry]


# ---------------------------------------------------------------------------
# Scan run models
# ---------------------------------------------------------------------------

class ScanRunCreate(BaseModel):
    host: str
    root_path: str
    started_at: datetime


class ScanRunPatch(BaseModel):
    status: str  # 'complete', 'failed', or 'interrupted'


class ScanRunResponse(BaseModel):
    id: int
    host: str
    root_path: str
    started_at: datetime
    status: str


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class UpsertResponse(BaseModel):
    upserted: int


class SeenResponse(BaseModel):
    updated: int


class ScanRunCreatedResponse(BaseModel):
    id: int


class CacheEntry(BaseModel):
    path: str
    mtime: Optional[int]
    size_bytes: Optional[int]


class CacheResponse(BaseModel):
    files: list[CacheEntry]


class LsEntry(BaseModel):
    segment: str
    entry_type: str  # 'file' | 'dir'
    file_count: int
    total_bytes: Optional[int]
    dup_count: int
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    hash: Optional[str] = None
    mtime: Optional[int] = None
    path_display: Optional[str] = None
    segment_display: Optional[str] = None
    other_hosts: Optional[str] = None


class FileEntry(BaseModel):
    host: str
    drive: str
    path_display: str
    filename: str
    ext: str
    file_category: str
    size_bytes: Optional[int]
    hash: Optional[str]
    mtime: Optional[int]
    other_hosts: Optional[str] = None


class HostEntry(BaseModel):
    host: str
    last_scan_at: Optional[datetime]
    last_scan_root: Optional[str]
    total_files: int
    total_bytes: Optional[int]
    total_hashed: int


class StatsOverview(BaseModel):
    total_files: int
    total_hosts: int
    unique_hashes: int
    duplicate_sets: int
    wasted_bytes: Optional[int]
    total_bytes: Optional[int]


class DuplicateLocation(BaseModel):
    host: str
    drive: str
    path_display: str


class DuplicateSet(BaseModel):
    hash: str
    filename: str
    size_bytes: Optional[int]
    copy_count: int
    wasted_bytes: Optional[int]
    locations: list[DuplicateLocation]
