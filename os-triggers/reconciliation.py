from __future__ import annotations

import logging
import os
from typing import Set

from identity_service import FileIdentityService
from models import FileStatus
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


class ReconciliationScanner:

    def __init__(
        self,
        watch_paths: list[str],
        identity_service: FileIdentityService,
        qdrant: QdrantClient,
    ) -> None:
        self._watch_paths = watch_paths
        self._identity = identity_service
        self._qdrant = qdrant

    def run(self) -> None:
        logger.info("=== Reconciliation scan started ===")
        disk_paths = self._scan_disk()
        self._sync_new_files(disk_paths)
        self._mark_missing(disk_paths)
        logger.info("=== Reconciliation scan completed (%d files on disk) ===", len(disk_paths))

    def _scan_disk(self) -> Set[str]:
        found: Set[str] = set()
        for root_path in self._watch_paths:
            norm_root = os.path.normpath(os.path.abspath(root_path))
            if not os.path.isdir(norm_root):
                continue
            for dirpath, _dirnames, filenames in os.walk(norm_root):
                for fn in filenames:
                    full = os.path.normpath(os.path.join(dirpath, fn))
                    found.add(full)
        return found

    def _sync_new_files(self, disk_paths: Set[str]) -> None:
        for path in disk_paths:
            existing = self._identity.get_by_path(path)
            if existing is None:
                identity = self._identity.register(path)
                self._qdrant.upsert_metadata(identity.file_id, identity.to_dict())
                logger.info("Reconciliation: registered %s -> %s", path, identity.file_id)

    def _mark_missing(self, disk_paths: Set[str]) -> None:
        for identity in self._identity.get_all():
            if identity.status != FileStatus.ACTIVE:
                continue
            if identity.current_path not in disk_paths:
                self._identity.handle_delete(identity.current_path)
                self._qdrant.delete_vector(identity.file_id)
                logger.info(
                    "Reconciliation: marked missing %s (%s)",
                    identity.current_path,
                    identity.file_id,
                )
