"""
Capture API Routes - Handle browser extension and OS capture events.

Processes incoming screenshots with vision model and stores to vector DB.
"""

import base64
import uuid
import asyncio
import os
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from enum import Enum
import redis

from core.ollama_client import OllamaClient, ModelRole
from memory.vector_store import VectorStore
from memory.knowledge_graph import KnowledgeGraph, extract_entities_from_text

router = APIRouter()

# Lazy-loaded services
_ollama_client: Optional[OllamaClient] = None
_vector_store: Optional[VectorStore] = None
_knowledge_graph: Optional[KnowledgeGraph] = None
_redis_client: Optional[redis.Redis] = None

# Redis keys for capture state (shared with system.py)
CAPTURE_KEY_PREFIX = "bmo:capture:"
EXTENSION_HEARTBEAT_KEY = f"{CAPTURE_KEY_PREFIX}extension_heartbeat"
OS_MONITOR_HEARTBEAT_KEY = f"{CAPTURE_KEY_PREFIX}os_monitor_heartbeat"
LAST_EVENT_KEY = f"{CAPTURE_KEY_PREFIX}last_event"
EVENTS_TODAY_KEY = f"{CAPTURE_KEY_PREFIX}events_today"
EVENTS_HOUR_KEY = f"{CAPTURE_KEY_PREFIX}events_hour"


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True
        )
    return _redis_client


def get_ollama_client() -> OllamaClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store


def get_knowledge_graph() -> KnowledgeGraph:
    global _knowledge_graph
    if _knowledge_graph is None:
        _knowledge_graph = KnowledgeGraph()
    return _knowledge_graph


def record_capture_event():
    """Record a capture event in Redis for statistics."""
    try:
        r = get_redis_client()
        now = datetime.now()
        
        # Update last event timestamp
        r.set(LAST_EVENT_KEY, now.isoformat())
        
        # Increment today's counter (expires at midnight)
        today_key = f"{EVENTS_TODAY_KEY}:{now.strftime('%Y-%m-%d')}"
        r.incr(today_key)
        r.expireat(today_key, datetime.combine(now.date() + timedelta(days=1), datetime.min.time()))
        
        # Also update the simple counter
        r.incr(EVENTS_TODAY_KEY)
        
        # Increment hourly counter (expires after 1 hour)
        hour_key = f"{EVENTS_HOUR_KEY}:{now.strftime('%Y-%m-%d-%H')}"
        r.incr(hour_key)
        r.expire(hour_key, 3600)
        
        # Also update the simple counter
        r.incr(EVENTS_HOUR_KEY)
        r.expire(EVENTS_HOUR_KEY, 3600)
        
    except Exception as e:
        print(f"[Capture] Redis error recording event: {e}")


class TriggerType(str, Enum):
    # High Intent & Extraction
    SELECTION_INTEREST = "selection_interest"
    COPY_CUT_ACTION = "copy_cut_action"
    CONTEXT_MENU = "context_menu"
    SEARCH_FOUND = "search_found"
    
    # Reading & Deep Engagement
    SCROLL_STOP_READ = "scroll_stop_read"
    ZOOM_DETAIL = "zoom_detail"
    DEEP_READ_DWELL = "deep_read_dwell"
    
    # Workflow & Comparison
    TAB_RETURN = "tab_return"
    APP_SWITCH = "app_switch"
    
    # Frustration Signals
    RAGE_CLICK = "rage_click"
    SCAN_SEARCH = "scan_search"
    
    # Social Media
    FACEBOOK_LIKE = "facebook_like"
    INSTAGRAM_LIKE = "instagram_like"
    
    # Legacy triggers
    DWELL = "dwell"
    SLOW_SCROLL = "slow_scroll"
    COPY = "copy"
    TAB_CHANGE = "tab_change"
    FRAME_DELTA = "frame_delta"
    FORCE = "force"


class CaptureEvent(BaseModel):
    trigger_type: TriggerType
    timestamp: datetime
    source_url: Optional[str] = None
    source_app: Optional[str] = None
    content_text: Optional[str] = None
    screenshot_base64: Optional[str] = None
    metadata: dict = {}


class CaptureResponse(BaseModel):
    event_id: str
    accepted: bool
    deduplicated: bool = False
    processing_queued: bool = False


class BulkCaptureRequest(BaseModel):
    events: List[CaptureEvent]


class BulkCaptureResponse(BaseModel):
    accepted_count: int
    deduplicated_count: int
    event_ids: List[str]


async def process_capture_event(event_id: str, event: CaptureEvent):
    """
    Background task to process a capture event:
    1. Analyze screenshot with vision model (if present)
    2. Extract entities from description
    3. Store in vector DB
    4. Update knowledge graph
    """
    try:
        ollama = get_ollama_client()
        vector_store = get_vector_store()
        knowledge_graph = get_knowledge_graph()
        
        description = ""
        
        # Process screenshot with vision model
        if event.screenshot_base64:
            prompt = (
                "Describe what the user is doing in this screenshot. "
                "Focus on: the application being used, files being edited, "
                "websites being browsed, and any visible content that indicates "
                "the user's current task or intent. Be specific about file names, "
                "URLs, and application names you can see."
            )
            
            # Use vision model to analyze screenshot
            result = await asyncio.to_thread(
                ollama.generate_with_image_sync,
                prompt,
                event.screenshot_base64,
                ModelRole.VISION
            )
            description = result.content
        elif event.content_text:
            description = event.content_text
        
        if not description:
            return
        
        # Add context from event metadata
        context_parts = [description]
        if event.source_url:
            context_parts.append(f"Source URL: {event.source_url}")
        if event.source_app:
            context_parts.append(f"Application: {event.source_app}")
        context_parts.append(f"Trigger: {event.trigger_type.value}")
        
        full_description = "\n".join(context_parts)
        
        # Extract entities for metadata
        entities = extract_entities_from_text(full_description)
        
        # Store in vector DB
        metadata = {
            "event_id": event_id,
            "trigger_type": event.trigger_type.value,
            "source_url": event.source_url,
            "source_app": event.source_app,
            "timestamp": event.timestamp.isoformat(),
            "files": [f["name"] for f in entities.files],
            "apps": [a["name"] for a in entities.apps],
            "websites": [w["name"] for w in entities.websites],
            "actions": entities.actions,
            "source": "browser",
        }
        
        await asyncio.to_thread(
            vector_store.add_sync,
            raw_text=full_description,
            category="uncategorized",
            source="browser",
            source_url=event.source_url,
            tags=metadata.get("actions", []),
            image_base64=event.screenshot_base64  # Store original screenshot
        )
        
        # Record event in Redis for statistics
        record_capture_event()
        
        # Update knowledge graph
        await asyncio.to_thread(
            knowledge_graph.ingest_activity,
            text=full_description,
            activity_id=event_id,
            timestamp=event.timestamp.isoformat(),
            activity_type=f"browser_{event.trigger_type.value}"
        )
        
    except Exception as e:
        # Log error but don't fail the request
        print(f"[Capture] Error processing event {event_id}: {e}")


@router.post("/event", response_model=CaptureResponse)
async def submit_capture_event(
    event: CaptureEvent,
    background_tasks: BackgroundTasks
):
    """Submit a single capture event for processing."""
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    
    accepted = bool(event.content_text or event.screenshot_base64)
    
    if accepted:
        background_tasks.add_task(process_capture_event, event_id, event)
    
    return CaptureResponse(
        event_id=event_id,
        accepted=accepted,
        deduplicated=False,
        processing_queued=accepted
    )


@router.post("/events/bulk", response_model=BulkCaptureResponse)
async def submit_bulk_events(
    request: BulkCaptureRequest,
    background_tasks: BackgroundTasks
):
    """Submit multiple capture events for processing."""
    event_ids = []
    accepted_count = 0
    
    for event in request.events:
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        event_ids.append(event_id)
        
        if event.content_text or event.screenshot_base64:
            accepted_count += 1
            background_tasks.add_task(process_capture_event, event_id, event)
    
    return BulkCaptureResponse(
        accepted_count=accepted_count,
        deduplicated_count=0,
        event_ids=event_ids
    )


@router.post("/screenshot")
async def submit_screenshot(
    screenshot_base64: str,
    background_tasks: BackgroundTasks,
    source_url: Optional[str] = None,
    trigger_type: TriggerType = TriggerType.FORCE
):
    """Submit a raw screenshot for processing."""
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    
    event = CaptureEvent(
        trigger_type=trigger_type,
        timestamp=datetime.now(),
        source_url=source_url,
        screenshot_base64=screenshot_base64
    )
    
    background_tasks.add_task(process_capture_event, event_id, event)
    
    return {
        "event_id": event_id,
        "processing_queued": True
    }


@router.get("/triggers/config")
async def get_trigger_config():
    """Get trigger configuration for browser extension."""
    return {
        # High Intent & Extraction
        "selection_interest": {
            "enabled": True,
            "charThreshold": 50,
            "debounceMs": 1000
        },
        "copy_cut_action": {"enabled": True},
        "context_menu": {"enabled": True},
        "search_found": {
            "enabled": True,
            "scrollThresholdPx": 100,
            "windowMs": 2000
        },
        
        # Reading & Deep Engagement
        "scroll_stop_read": {
            "enabled": True,
            "minVelocity": 0.3,
            "stillMs": 3000
        },
        "zoom_detail": {"enabled": True},
        "deep_read_dwell": {
            "enabled": True,
            "idleMs": 10000
        },
        
        # Workflow & Comparison
        "tab_return": {
            "enabled": True,
            "delayMs": 500
        },
        "app_switch": {"enabled": True},
        
        # Frustration Signals
        "rage_click": {
            "enabled": True,
            "clickCount": 3,
            "windowMs": 1000
        },
        "scan_search": {
            "enabled": True,
            "directionChanges": 2,
            "windowMs": 2000
        },
        
        # Social Media
        "facebook_like": {
            "enabled": True,
            "confirmMs": 600
        },
        "instagram_like": {
            "enabled": True,
            "confirmMs": 600
        }
    }


@router.post("/extension/connect")
async def extension_connect(extension_id: str):
    """Register browser extension connection and set heartbeat."""
    try:
        r = get_redis_client()
        r.set(EXTENSION_HEARTBEAT_KEY, datetime.now().isoformat())
    except Exception as e:
        print(f"[Capture] Redis error setting extension heartbeat: {e}")
    return {"status": "connected", "extension_id": extension_id}


@router.post("/extension/heartbeat")
async def extension_heartbeat(extension_id: str):
    """Update browser extension heartbeat."""
    try:
        r = get_redis_client()
        r.set(EXTENSION_HEARTBEAT_KEY, datetime.now().isoformat())
    except Exception as e:
        print(f"[Capture] Redis error updating extension heartbeat: {e}")
    return {"status": "ok"}


@router.post("/extension/disconnect")
async def extension_disconnect(extension_id: str):
    """Unregister browser extension connection."""
    try:
        r = get_redis_client()
        r.delete(EXTENSION_HEARTBEAT_KEY)
    except Exception as e:
        print(f"[Capture] Redis error clearing extension heartbeat: {e}")
    return {"status": "disconnected"}


@router.post("/folder/ingest")
async def ingest_folder_screenshots(background_tasks: BackgroundTasks):
    """Ingest all existing screenshots from the capture folder."""
    from capture.screenshot_watcher import get_screenshot_watcher
    import logging
    
    logger = logging.getLogger(__name__)
    
    async def run_ingest():
        try:
            logger.info("[FolderIngest] Starting screenshot ingestion...")
            watcher = get_screenshot_watcher()
            count = await watcher.ingest_existing()
            logger.info(f"[FolderIngest] Completed: {count} screenshots processed")
            return count
        except Exception as e:
            logger.error(f"[FolderIngest] Error: {e}", exc_info=True)
            raise
    
    # Schedule the coroutine properly
    asyncio.create_task(run_ingest())
    
    return {
        "status": "ingestion_started",
        "message": "Processing screenshots in background"
    }


@router.post("/folder/start-watcher")
async def start_folder_watcher():
    """Start watching the capture folder for new screenshots."""
    from capture.screenshot_watcher import get_screenshot_watcher
    
    watcher = get_screenshot_watcher()
    
    if watcher.is_running:
        return {"status": "already_running", "folder": watcher._folder}
    
    watcher.start()
    return {"status": "started", "folder": watcher._folder}


@router.post("/folder/stop-watcher")
async def stop_folder_watcher():
    """Stop watching the capture folder."""
    from capture.screenshot_watcher import get_screenshot_watcher
    
    watcher = get_screenshot_watcher()
    watcher.stop()
    return {"status": "stopped"}


@router.get("/folder/status")
async def get_folder_watcher_status():
    """Get the status of the folder watcher."""
    from capture.screenshot_watcher import get_screenshot_watcher, DEFAULT_CAPTURE_FOLDER
    import os
    
    watcher = get_screenshot_watcher()
    folder = watcher._folder
    
    file_count = 0
    if os.path.exists(folder):
        file_count = len([f for f in os.listdir(folder) if f.endswith('.png')])
    
    return {
        "watcher_running": watcher.is_running,
        "folder": folder,
        "folder_exists": os.path.exists(folder),
        "file_count": file_count,
        "processed_count": len(watcher._processed_files)
    }
