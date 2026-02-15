from __future__ import annotations

import logging
from typing import Optional

from bmo.capture.os_monitor.models import EventType, FileState

logger = logging.getLogger(__name__)

_TRANSITIONS: dict[FileState, dict[EventType, FileState]] = {
    FileState.NEW: {
        EventType.FILE_CREATED: FileState.ACTIVE,
        EventType.DIRECTORY_CREATED: FileState.ACTIVE,
    },
    FileState.ACTIVE: {
        EventType.FILE_MODIFIED: FileState.MODIFIED,
        EventType.FILE_RENAMED: FileState.RENAMED,
        EventType.FILE_MOVED: FileState.MOVED,
        EventType.FILE_DELETED: FileState.DELETED,
        EventType.DIRECTORY_RENAMED: FileState.RENAMED,
        EventType.DIRECTORY_MOVED: FileState.MOVED,
        EventType.DIRECTORY_DELETED: FileState.DELETED,
    },
    FileState.MODIFIED: {
        EventType.FILE_MODIFIED: FileState.MODIFIED,
        EventType.FILE_RENAMED: FileState.RENAMED,
        EventType.FILE_MOVED: FileState.MOVED,
        EventType.FILE_DELETED: FileState.DELETED,
    },
    FileState.MOVED: {
        EventType.FILE_MODIFIED: FileState.MODIFIED,
        EventType.FILE_RENAMED: FileState.RENAMED,
        EventType.FILE_MOVED: FileState.MOVED,
        EventType.FILE_DELETED: FileState.DELETED,
        EventType.DIRECTORY_RENAMED: FileState.RENAMED,
        EventType.DIRECTORY_MOVED: FileState.MOVED,
        EventType.DIRECTORY_DELETED: FileState.DELETED,
    },
    FileState.RENAMED: {
        EventType.FILE_MODIFIED: FileState.MODIFIED,
        EventType.FILE_RENAMED: FileState.RENAMED,
        EventType.FILE_MOVED: FileState.MOVED,
        EventType.FILE_DELETED: FileState.DELETED,
        EventType.DIRECTORY_RENAMED: FileState.RENAMED,
        EventType.DIRECTORY_MOVED: FileState.MOVED,
        EventType.DIRECTORY_DELETED: FileState.DELETED,
    },
    FileState.DELETED: {
        EventType.FILE_CREATED: FileState.ACTIVE,
        EventType.DIRECTORY_CREATED: FileState.ACTIVE,
    },
    FileState.PURGED: {},
}


class StateMachine:

    def transition(self, current_state: FileState, event_type: EventType) -> Optional[FileState]:
        allowed = _TRANSITIONS.get(current_state, {})
        next_state = allowed.get(event_type)
        if next_state is None:
            logger.warning(
                "No valid transition from state=%s on event=%s",
                current_state.value,
                event_type.value,
            )
            return None
        logger.info(
            "State transition: %s -[%s]-> %s",
            current_state.value,
            event_type.value,
            next_state.value,
        )
        return next_state

    @staticmethod
    def can_purge(current_state: FileState) -> bool:
        return current_state == FileState.DELETED
