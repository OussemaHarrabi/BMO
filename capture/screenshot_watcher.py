"""
Screenshot Folder Watcher - Monitors InterestCapture folder for new screenshots.

Processes images with vision model and stores in Qdrant vector database.
"""

import os
import base64
import asyncio
import logging
import re
import threading
from datetime import datetime
from typing import Optional, Set
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from watchdog.observers import Observer

# Configure logging to show in Docker
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_CAPTURE_FOLDER = r"C:\Users\DELL\Downloads\InterestCapture\captures"

TRIGGER_PATTERN = re.compile(
    r'^(app_switch|deep_read_dwell|scan_search|scroll_stop_read|tab_return|'
    r'selection_interest|copy_cut_action|context_menu|search_found|zoom_detail|'
    r'rage_click|facebook_like|instagram_like|dwell|slow_scroll|copy|tab_change|'
    r'frame_delta|force)_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z)\.png$'
)


def parse_filename(filename: str) -> tuple[Optional[str], Optional[datetime]]:
    """Extract trigger type and timestamp from filename."""
    match = TRIGGER_PATTERN.match(filename)
    if not match:
        return None, None
    
    trigger_type = match.group(1)
    timestamp_str = match.group(2)
    
    try:
        ts_normalized = timestamp_str.replace('-', ':', 2).replace('-', '.', 1)
        ts_normalized = ts_normalized.replace('T', ' ').replace('Z', '')
        ts_parts = ts_normalized.split(' ')
        date_part = ts_parts[0].replace(':', '-')
        time_part = ts_parts[1] if len(ts_parts) > 1 else "00:00:00.000"
        time_part = time_part.replace('-', ':')
        
        dt_str = f"{date_part}T{time_part}"
        timestamp = datetime.fromisoformat(dt_str.replace('.', ':').rsplit(':', 1)[0])
    except Exception as e:
        logger.warning(f"Failed to parse timestamp from {filename}: {e}")
        timestamp = datetime.now()
    
    return trigger_type, timestamp


class ScreenshotHandler(FileSystemEventHandler):
    
    def __init__(self, processor_callback):
        super().__init__()
        self._processor = processor_callback
        self._processed: Set[str] = set()
        self._lock = threading.Lock()
    
    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        
        filepath = event.src_path
        filename = os.path.basename(filepath)
        
        if not filename.lower().endswith('.png'):
            return
        
        with self._lock:
            if filepath in self._processed:
                return
            self._processed.add(filepath)
        
        logger.info(f"[ScreenshotWatcher] New capture detected: {filename}")
        
        try:
            asyncio.get_event_loop().call_soon_threadsafe(
                lambda: asyncio.create_task(self._processor(filepath))
            )
        except RuntimeError:
            threading.Thread(
                target=lambda: asyncio.run(self._processor(filepath)),
                daemon=True
            ).start()


class ScreenshotWatcher:
    
    def __init__(
        self,
        capture_folder: str = DEFAULT_CAPTURE_FOLDER,
        ollama_client=None,
        vector_store=None
    ):
        self._folder = capture_folder
        self._ollama = ollama_client
        self._vector_store = vector_store
        self._observer: Optional[Observer] = None
        self._handler: Optional[ScreenshotHandler] = None
        self._processed_files: Set[str] = set()
        self._running = False
    
    def _get_ollama(self):
        if self._ollama is None:
            from core.ollama_client import OllamaClient
            self._ollama = OllamaClient()
        return self._ollama
    
    def _get_vector_store(self):
        if self._vector_store is None:
            from memory.vector_store import VectorStore
            self._vector_store = VectorStore()
        return self._vector_store
    
    async def process_screenshot(self, filepath: str) -> bool:
        """Process a single screenshot: analyze with vision model and store."""
        filename = os.path.basename(filepath)
        trigger_type, timestamp = parse_filename(filename)
        
        if not trigger_type:
            logger.warning(f"[ScreenshotWatcher] Invalid filename format: {filename}")
            return False
        
        try:
            with open(filepath, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"[ScreenshotWatcher] Failed to read {filename}: {e}")
            return False
        
        prompt = (
            "Describe what the user is doing in this screenshot. "
            "Focus on: the application being used, files being edited, "
            "websites being browsed, and any visible content that indicates "
            "the user's current task or intent. Be specific about file names, "
            "URLs, and application names you can see. "
            "Also note any text visible on screen."
        )
        
        try:
            from core.ollama_client import ModelRole
            ollama = self._get_ollama()
            
            result = ollama.generate_with_image_sync(
                prompt=prompt,
                image_base64=image_data,
                role=ModelRole.VISION,
                temperature=0.3,
                max_tokens=500
            )
            description = result.content.strip()
            logger.info(f"[ScreenshotWatcher] Vision analysis complete for {filename}")
        except Exception as e:
            logger.error(f"[ScreenshotWatcher] Vision analysis failed: {e}")
            description = f"Screenshot captured via {trigger_type} trigger"
        
        context_parts = [description]
        context_parts.append(f"Trigger: {trigger_type}")
        context_parts.append(f"Source: screenshot_capture")
        full_description = "\n".join(context_parts)
        
        try:
            vector_store = self._get_vector_store()
            vector_store.add_sync(
                raw_text=full_description,
                category="uncategorized",
                source="screenshot",
                source_path=filepath,
                tags=[trigger_type, "screenshot", "capture"],
                image_base64=image_data
            )
            logger.info(f"[ScreenshotWatcher] Stored in vector DB: {filename}")
            
            self._update_redis_stats()
            
            return True
        except Exception as e:
            logger.error(f"[ScreenshotWatcher] Failed to store {filename}: {e}")
            return False
    
    def _update_redis_stats(self):
        """Update Redis capture statistics."""
        try:
            import redis
            from datetime import timedelta
            
            r = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                decode_responses=True
            )
            
            now = datetime.now()
            
            r.set("bmo:capture:os_monitor_heartbeat", now.isoformat())
            r.set("bmo:capture:last_event", now.isoformat())
            
            today_key = f"bmo:capture:events_today:{now.strftime('%Y-%m-%d')}"
            r.incr(today_key)
            r.expireat(today_key, datetime.combine(
                now.date() + timedelta(days=1), 
                datetime.min.time()
            ))
            r.incr("bmo:capture:events_today")
            
            hour_key = f"bmo:capture:events_hour:{now.strftime('%Y-%m-%d-%H')}"
            r.incr(hour_key)
            r.expire(hour_key, 3600)
            r.incr("bmo:capture:events_hour")
            r.expire("bmo:capture:events_hour", 3600)
            
        except Exception as e:
            logger.warning(f"[ScreenshotWatcher] Redis update failed: {e}")
    
    async def ingest_existing(self) -> int:
        """Process all existing screenshots in the folder."""
        if not os.path.exists(self._folder):
            logger.warning(f"[ScreenshotWatcher] Folder not found: {self._folder}")
            return 0
        
        files = sorted([
            f for f in os.listdir(self._folder) 
            if f.lower().endswith('.png')
        ])
        
        logger.info(f"[ScreenshotWatcher] Found {len(files)} existing screenshots")
        
        processed = 0
        for filename in files:
            filepath = os.path.join(self._folder, filename)
            
            if filepath in self._processed_files:
                continue
            
            if await self.process_screenshot(filepath):
                processed += 1
                self._processed_files.add(filepath)
            
            await asyncio.sleep(0.5)
        
        logger.info(f"[ScreenshotWatcher] Ingested {processed}/{len(files)} screenshots")
        return processed
    
    def start(self):
        """Start watching the capture folder."""
        if self._running:
            return
        
        if not os.path.exists(self._folder):
            os.makedirs(self._folder, exist_ok=True)
            logger.info(f"[ScreenshotWatcher] Created folder: {self._folder}")
        
        self._handler = ScreenshotHandler(self.process_screenshot)
        self._observer = Observer()
        self._observer.schedule(self._handler, self._folder, recursive=False)
        self._observer.start()
        self._running = True
        
        logger.info(f"[ScreenshotWatcher] Watching: {self._folder}")
    
    def stop(self):
        """Stop watching."""
        if not self._running:
            return
        
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        
        self._running = False
        logger.info("[ScreenshotWatcher] Stopped")
    
    @property
    def is_running(self) -> bool:
        return self._running


_watcher_instance: Optional[ScreenshotWatcher] = None


def get_screenshot_watcher() -> ScreenshotWatcher:
    global _watcher_instance
    if _watcher_instance is None:
        folder = os.getenv("CAPTURE_FOLDER_PATH", DEFAULT_CAPTURE_FOLDER)
        _watcher_instance = ScreenshotWatcher(capture_folder=folder)
    return _watcher_instance


async def start_screenshot_watcher():
    watcher = get_screenshot_watcher()
    watcher.start()
    return watcher


async def ingest_existing_screenshots() -> int:
    watcher = get_screenshot_watcher()
    return await watcher.ingest_existing()
