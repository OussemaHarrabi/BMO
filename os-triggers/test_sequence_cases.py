from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from document_processor import DocumentProcessor
from embedding_service import EmbeddingService
from event_queue import EventQueue
from identity_service import FileIdentityService
from models import EventType, FileState, FileStatus, FSEvent
from qdrant_client import QdrantClient
from reconciliation import ReconciliationScanner
from state_machine import StateMachine
from watcher import FileWatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test")

EVENT_SETTLE_SEC = 1.5


class _Harness:

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self.identity = FileIdentityService()
        self.qdrant = QdrantClient()
        self.embedding = EmbeddingService()
        self.processor = DocumentProcessor(self.identity, self.qdrant, self.embedding)
        self.events: list[FSEvent] = []

        def _handler(ev: FSEvent) -> None:
            self.events.append(ev)
            self.processor.process(ev)

        self.queue = EventQueue(handler=_handler)
        self.queue.start()
        self.watcher = FileWatcher(paths=[base_dir], emit=self.queue.enqueue)
        self.watcher.start()

    def settle(self, seconds: float = EVENT_SETTLE_SEC) -> None:
        time.sleep(seconds)
        self.queue.drain()

    def teardown(self) -> None:
        self.watcher.stop()
        self.queue.drain()
        self.queue.stop()


class TestStateMachine(unittest.TestCase):

    def test_new_to_active(self) -> None:
        sm = StateMachine()
        ns = sm.transition(FileState.NEW, EventType.FILE_CREATED)
        self.assertEqual(ns, FileState.ACTIVE)

    def test_active_to_modified(self) -> None:
        sm = StateMachine()
        ns = sm.transition(FileState.ACTIVE, EventType.FILE_MODIFIED)
        self.assertEqual(ns, FileState.MODIFIED)

    def test_active_to_renamed(self) -> None:
        sm = StateMachine()
        ns = sm.transition(FileState.ACTIVE, EventType.FILE_RENAMED)
        self.assertEqual(ns, FileState.RENAMED)

    def test_active_to_moved(self) -> None:
        sm = StateMachine()
        ns = sm.transition(FileState.ACTIVE, EventType.FILE_MOVED)
        self.assertEqual(ns, FileState.MOVED)

    def test_active_to_deleted(self) -> None:
        sm = StateMachine()
        ns = sm.transition(FileState.ACTIVE, EventType.FILE_DELETED)
        self.assertEqual(ns, FileState.DELETED)

    def test_deleted_to_active_on_recreate(self) -> None:
        sm = StateMachine()
        ns = sm.transition(FileState.DELETED, EventType.FILE_CREATED)
        self.assertEqual(ns, FileState.ACTIVE)

    def test_invalid_transition(self) -> None:
        sm = StateMachine()
        ns = sm.transition(FileState.PURGED, EventType.FILE_MODIFIED)
        self.assertIsNone(ns)

    def test_can_purge(self) -> None:
        self.assertTrue(StateMachine.can_purge(FileState.DELETED))
        self.assertFalse(StateMachine.can_purge(FileState.ACTIVE))


class TestIdentityService(unittest.TestCase):

    def setUp(self) -> None:
        self.svc = FileIdentityService()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, content: str = "hello") -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_register_and_lookup(self) -> None:
        path = self._write("a.txt")
        identity = self.svc.register(path)
        self.assertEqual(identity.status, FileStatus.ACTIVE)
        self.assertIsNotNone(identity.content_hash)
        same = self.svc.get_by_path(path)
        self.assertEqual(identity.file_id, same.file_id)

    def test_modify_updates_hash(self) -> None:
        path = self._write("b.txt", "v1")
        identity = self.svc.register(path)
        old_hash = identity.content_hash
        with open(path, "w") as f:
            f.write("v2")
        updated = self.svc.handle_modify(path)
        self.assertNotEqual(old_hash, updated.content_hash)

    def test_delete_marks_deleted(self) -> None:
        path = self._write("c.txt")
        identity = self.svc.register(path)
        deleted = self.svc.handle_delete(path)
        self.assertEqual(deleted.status, FileStatus.DELETED)
        self.assertIsNone(self.svc.get_by_path(path))

    def test_restore_on_same_hash(self) -> None:
        path = self._write("d.txt", "content123")
        identity = self.svc.register(path)
        fid = identity.file_id
        self.svc.handle_delete(path)
        with open(path, "w") as f:
            f.write("content123")
        restored = self.svc.register(path)
        self.assertEqual(restored.file_id, fid)
        self.assertEqual(restored.status, FileStatus.ACTIVE)

    def test_rename(self) -> None:
        path = self._write("e.txt")
        identity = self.svc.register(path)
        new_path = os.path.join(self.tmp, "e_renamed.txt")
        os.rename(path, new_path)
        renamed = self.svc.handle_rename(path, new_path)
        self.assertEqual(renamed.file_id, identity.file_id)
        self.assertIn(os.path.normpath(os.path.abspath(new_path)), renamed.current_path)

    def test_purge(self) -> None:
        path = self._write("f.txt")
        identity = self.svc.register(path)
        self.svc.handle_delete(path)
        result = self.svc.purge(identity.file_id)
        self.assertTrue(result)
        self.assertIsNone(self.svc.get_by_id(identity.file_id))


class TestEventQueue(unittest.TestCase):

    def test_sequential_processing(self) -> None:
        results: list[str] = []

        def handler(ev: FSEvent) -> None:
            results.append(ev.event_type.value)
            time.sleep(0.05)

        q = EventQueue(handler=handler)
        q.start()
        types = [EventType.FILE_CREATED, EventType.FILE_MODIFIED, EventType.FILE_DELETED]
        for et in types:
            q.enqueue(FSEvent(event_type=et, path="/fake"))
        q.drain()
        q.stop()
        self.assertEqual(results, [t.value for t in types])


class TestLiveCreate(unittest.TestCase):

    def test_create_file(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            h = _Harness(tmp)
            path = os.path.join(tmp, "new_file.txt")
            with open(path, "w") as f:
                f.write("hello world")
            h.settle()
            identity = h.identity.get_by_path(path)
            self.assertIsNotNone(identity)
            self.assertEqual(identity.status, FileStatus.ACTIVE)
            created_events = [e for e in h.events if e.event_type == EventType.FILE_CREATED]
            self.assertGreaterEqual(len(created_events), 1)
            h.teardown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLiveModify(unittest.TestCase):

    def test_modify_file(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            h = _Harness(tmp)
            path = os.path.join(tmp, "mod_file.txt")
            with open(path, "w") as f:
                f.write("v1")
            h.settle()
            with open(path, "w") as f:
                f.write("v2 modified content")
            h.settle()
            identity = h.identity.get_by_path(path)
            self.assertIsNotNone(identity)
            has_modify = any(e.event_type == EventType.FILE_MODIFIED for e in h.events)
            self.assertTrue(has_modify)
            h.teardown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLiveRename(unittest.TestCase):

    def test_rename_file(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            h = _Harness(tmp)
            path = os.path.join(tmp, "original.txt")
            with open(path, "w") as f:
                f.write("data")
            h.settle()
            new_path = os.path.join(tmp, "renamed.txt")
            os.rename(path, new_path)
            h.settle()
            identity = h.identity.get_by_path(new_path)
            self.assertIsNotNone(identity)
            h.teardown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLiveMove(unittest.TestCase):

    def test_move_file(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            sub = os.path.join(tmp, "subdir")
            os.makedirs(sub)
            h = _Harness(tmp)
            path = os.path.join(tmp, "moveme.txt")
            with open(path, "w") as f:
                f.write("moveable")
            h.settle()
            dest = os.path.join(sub, "moveme.txt")
            shutil.move(path, dest)
            h.settle()
            identity = h.identity.get_by_path(dest)
            self.assertIsNotNone(identity)
            h.teardown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLiveDelete(unittest.TestCase):

    def test_delete_file(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            h = _Harness(tmp)
            path = os.path.join(tmp, "deleteme.txt")
            with open(path, "w") as f:
                f.write("bye")
            h.settle()
            os.remove(path)
            h.settle()
            identity = h.identity.get_by_path(path)
            self.assertIsNone(identity)
            has_delete = any(e.event_type == EventType.FILE_DELETED for e in h.events)
            self.assertTrue(has_delete)
            h.teardown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLiveNestedFolder(unittest.TestCase):

    def test_nested_create(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            h = _Harness(tmp)
            nested = os.path.join(tmp, "a", "b", "c")
            os.makedirs(nested)
            path = os.path.join(nested, "deep.txt")
            with open(path, "w") as f:
                f.write("nested content")
            h.settle()
            identity = h.identity.get_by_path(path)
            self.assertIsNotNone(identity)
            h.teardown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestBurstOperations(unittest.TestCase):

    def test_burst_creates(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            h = _Harness(tmp)
            paths = []
            for i in range(20):
                p = os.path.join(tmp, f"burst_{i}.txt")
                with open(p, "w") as f:
                    f.write(f"burst content {i}")
                paths.append(p)
            h.settle(3.0)
            found = 0
            for p in paths:
                if h.identity.get_by_path(p):
                    found += 1
            self.assertGreaterEqual(found, 15)
            h.teardown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestMassDeletion(unittest.TestCase):

    def test_mass_delete(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            h = _Harness(tmp)
            paths = []
            for i in range(10):
                p = os.path.join(tmp, f"mass_{i}.txt")
                with open(p, "w") as f:
                    f.write(f"mass {i}")
                paths.append(p)
            h.settle(2.0)
            for p in paths:
                if os.path.exists(p):
                    os.remove(p)
            h.settle(2.0)
            deleted_count = sum(1 for p in paths if h.identity.get_by_path(p) is None)
            self.assertGreaterEqual(deleted_count, 8)
            h.teardown()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestReconciliation(unittest.TestCase):

    def test_reconciliation_discovers_existing(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            for i in range(3):
                with open(os.path.join(tmp, f"existing_{i}.txt"), "w") as f:
                    f.write(f"pre-existing {i}")
            identity_svc = FileIdentityService()
            qdrant = QdrantClient()
            scanner = ReconciliationScanner(
                watch_paths=[tmp],
                identity_service=identity_svc,
                qdrant=qdrant,
            )
            scanner.run()
            for i in range(3):
                path = os.path.join(tmp, f"existing_{i}.txt")
                self.assertIsNotNone(identity_svc.get_by_path(path))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_reconciliation_marks_missing(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "ghost.txt")
            with open(path, "w") as f:
                f.write("ghost")
            identity_svc = FileIdentityService()
            qdrant = QdrantClient()
            identity_svc.register(path)
            os.remove(path)
            scanner = ReconciliationScanner(
                watch_paths=[tmp],
                identity_service=identity_svc,
                qdrant=qdrant,
            )
            scanner.run()
            ident = identity_svc.get_by_id(identity_svc.get_all()[0].file_id)
            self.assertEqual(ident.status, FileStatus.DELETED)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
