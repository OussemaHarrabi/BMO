from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class EventType(str, enum.Enum):
    FILE_CREATED = "file_created"
    FILE_MODIFIED = "file_modified"
    FILE_DELETED = "file_deleted"
    FILE_RENAMED = "file_renamed"
    FILE_MOVED = "file_moved"
    DIRECTORY_CREATED = "directory_created"
    DIRECTORY_DELETED = "directory_deleted"
    DIRECTORY_RENAMED = "directory_renamed"
    DIRECTORY_MOVED = "directory_moved"


class FileStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETED = "deleted"
    TRASHED = "trashed"


class FileState(str, enum.Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    MOVED = "MOVED"
    RENAMED = "RENAMED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    PURGED = "PURGED"


@dataclass
class FSEvent:
    event_type: EventType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    src_path: Optional[str] = None
    dest_path: Optional[str] = None
    path: Optional[str] = None
    is_directory: bool = False

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "src_path": self.src_path,
            "dest_path": self.dest_path,
            "path": self.path,
            "timestamp": self.timestamp,
            "is_directory": self.is_directory,
        }


@dataclass
class FileIdentity:
    file_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content_hash: Optional[str] = None
    original_created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    current_path: str = ""
    status: FileStatus = FileStatus.ACTIVE
    state: FileState = FileState.NEW

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "content_hash": self.content_hash,
            "original_created_at": self.original_created_at,
            "current_path": self.current_path,
            "status": self.status.value,
            "state": self.state.value,
        }
