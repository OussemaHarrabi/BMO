from __future__ import annotations

import hashlib
import logging
import os
import threading
from typing import Optional

from models import EventType, FileIdentity, FileState, FileStatus
from state_machine import StateMachine

logger = logging.getLogger(__name__)

_BUFFER_SIZE = 65536


def _compute_hash(path: str) -> Optional[str]:
    try:
        sha = hashlib.sha256()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_BUFFER_SIZE)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()
    except (OSError, IOError):
        return None


class FileIdentityService:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_path: dict[str, FileIdentity] = {}
        self._by_hash: dict[str, list[FileIdentity]] = {}
        self._by_id: dict[str, FileIdentity] = {}
        self._state_machine = StateMachine()

    def _normalize(self, path: str) -> str:
        return os.path.normpath(os.path.abspath(path))

    def _index_hash(self, identity: FileIdentity) -> None:
        if identity.content_hash:
            self._by_hash.setdefault(identity.content_hash, [])
            if identity not in self._by_hash[identity.content_hash]:
                self._by_hash[identity.content_hash].append(identity)

    def _unindex_hash(self, identity: FileIdentity) -> None:
        if identity.content_hash and identity.content_hash in self._by_hash:
            entries = self._by_hash[identity.content_hash]
            self._by_hash[identity.content_hash] = [e for e in entries if e.file_id != identity.file_id]
            if not self._by_hash[identity.content_hash]:
                del self._by_hash[identity.content_hash]

    def get_by_path(self, path: str) -> Optional[FileIdentity]:
        with self._lock:
            return self._by_path.get(self._normalize(path))

    def get_by_id(self, file_id: str) -> Optional[FileIdentity]:
        with self._lock:
            return self._by_id.get(file_id)

    def get_all(self) -> list[FileIdentity]:
        with self._lock:
            return list(self._by_id.values())

    def register(self, path: str, is_directory: bool = False) -> FileIdentity:
        norm = self._normalize(path)
        with self._lock:
            existing = self._by_path.get(norm)
            if existing and existing.status == FileStatus.ACTIVE:
                return existing

            content_hash = None if is_directory else _compute_hash(norm)

            if content_hash:
                candidates = self._by_hash.get(content_hash, [])
                for candidate in candidates:
                    if candidate.status == FileStatus.DELETED:
                        logger.info(
                            "Restoring identity %s (hash match) at %s",
                            candidate.file_id,
                            norm,
                        )
                        old_path = candidate.current_path
                        if old_path in self._by_path and self._by_path[old_path].file_id == candidate.file_id:
                            del self._by_path[old_path]
                        candidate.current_path = norm
                        candidate.status = FileStatus.ACTIVE
                        candidate.state = FileState.ACTIVE
                        self._by_path[norm] = candidate
                        return candidate

            identity = FileIdentity(
                current_path=norm,
                content_hash=content_hash,
                status=FileStatus.ACTIVE,
                state=FileState.NEW,
            )
            ns = self._state_machine.transition(identity.state, EventType.FILE_CREATED)
            if ns:
                identity.state = ns
            self._by_path[norm] = identity
            self._by_id[identity.file_id] = identity
            self._index_hash(identity)
            logger.info("Registered new identity %s for %s", identity.file_id, norm)
            return identity

    def handle_modify(self, path: str) -> Optional[FileIdentity]:
        norm = self._normalize(path)
        with self._lock:
            identity = self._by_path.get(norm)
            if not identity:
                return None
            self._unindex_hash(identity)
            identity.content_hash = _compute_hash(norm)
            self._index_hash(identity)
            ns = self._state_machine.transition(identity.state, EventType.FILE_MODIFIED)
            if ns:
                identity.state = ns
            logger.info("Modified identity %s hash=%s", identity.file_id, identity.content_hash)
            return identity

    def handle_delete(self, path: str) -> Optional[FileIdentity]:
        norm = self._normalize(path)
        with self._lock:
            identity = self._by_path.get(norm)
            if not identity:
                return None
            identity.status = FileStatus.DELETED
            ns = self._state_machine.transition(identity.state, EventType.FILE_DELETED)
            if ns:
                identity.state = ns
            del self._by_path[norm]
            logger.info("Marked deleted identity %s at %s", identity.file_id, norm)
            return identity

    def handle_rename(self, src: str, dest: str) -> Optional[FileIdentity]:
        src_n = self._normalize(src)
        dest_n = self._normalize(dest)
        with self._lock:
            identity = self._by_path.get(src_n)
            if not identity:
                return None
            del self._by_path[src_n]
            identity.current_path = dest_n
            self._by_path[dest_n] = identity

            src_dir = os.path.dirname(src_n)
            dest_dir = os.path.dirname(dest_n)
            if src_dir == dest_dir:
                event = EventType.FILE_RENAMED
            else:
                event = EventType.FILE_MOVED

            ns = self._state_machine.transition(identity.state, event)
            if ns:
                identity.state = ns
            logger.info(
                "Rename/move identity %s: %s -> %s (event=%s)",
                identity.file_id,
                src_n,
                dest_n,
                event.value,
            )
            return identity

    def handle_move(self, src: str, dest: str) -> Optional[FileIdentity]:
        return self.handle_rename(src, dest)

    def purge(self, file_id: str) -> bool:
        with self._lock:
            identity = self._by_id.get(file_id)
            if not identity:
                return False
            if not StateMachine.can_purge(identity.state):
                logger.warning("Cannot purge identity %s in state %s", file_id, identity.state.value)
                return False
            identity.state = FileState.PURGED
            identity.status = FileStatus.DELETED
            self._unindex_hash(identity)
            if identity.current_path in self._by_path:
                del self._by_path[identity.current_path]
            del self._by_id[file_id]
            logger.info("Purged identity %s", file_id)
            return True
