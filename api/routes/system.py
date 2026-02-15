from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import os
import redis

router = APIRouter()

# Redis client for capture state tracking
_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True
        )
    return _redis_client

# Redis keys for capture state
CAPTURE_KEY_PREFIX = "bmo:capture:"
EXTENSION_HEARTBEAT_KEY = f"{CAPTURE_KEY_PREFIX}extension_heartbeat"
OS_MONITOR_HEARTBEAT_KEY = f"{CAPTURE_KEY_PREFIX}os_monitor_heartbeat"
LAST_EVENT_KEY = f"{CAPTURE_KEY_PREFIX}last_event"
EVENTS_TODAY_KEY = f"{CAPTURE_KEY_PREFIX}events_today"
EVENTS_HOUR_KEY = f"{CAPTURE_KEY_PREFIX}events_hour"

# Heartbeat timeout (consider disconnected after this many seconds)
HEARTBEAT_TIMEOUT_SECONDS = 30


class SystemStatus(BaseModel):
    status: str
    uptime_seconds: int
    components: Dict[str, Any]
    models_loaded: Dict[str, bool]
    capture_active: bool
    last_capture: Optional[datetime]


class ModelStatus(BaseModel):
    name: str
    loaded: bool
    last_used: Optional[datetime]
    avg_latency_ms: Optional[float]


class CaptureStatus(BaseModel):
    os_monitor_active: bool
    browser_extension_connected: bool
    last_event_timestamp: Optional[datetime]
    events_today: int
    events_this_hour: int


_start_time = datetime.now()


@router.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/status", response_model=SystemStatus)
async def get_system_status():
    from core.ollama_client import OllamaClient
    
    client = OllamaClient()
    is_healthy = await client.health_check()
    
    models = await client.list_models()
    model_names = [m.get("name", "") for m in models]
    
    models_loaded = {
        "phi3.5": any("phi3.5" in n for n in model_names),
        "qwen3": any("qwen3" in n for n in model_names),
        "nomic-embed-text": any("nomic-embed-text" in n for n in model_names)
    }
    
    uptime = (datetime.now() - _start_time).total_seconds()
    
    return SystemStatus(
        status="healthy" if is_healthy else "degraded",
        uptime_seconds=int(uptime),
        components={
            "ollama": is_healthy,
            "qdrant": True,
            "neo4j": True,
            "redis": True
        },
        models_loaded=models_loaded,
        capture_active=False,
        last_capture=None
    )


@router.get("/models", response_model=Dict[str, ModelStatus])
async def get_model_status():
    from core.ollama_client import OllamaClient
    
    client = OllamaClient()
    models = await client.list_models()
    
    result = {}
    for model in models:
        name = model.get("name", "unknown")
        result[name] = ModelStatus(
            name=name,
            loaded=True,
            last_used=None,
            avg_latency_ms=None
        )
    
    return result


@router.post("/models/{model_name}/load")
async def load_model(model_name: str, background_tasks: BackgroundTasks):
    from core.ollama_client import OllamaClient
    
    async def pull_model():
        client = OllamaClient()
        await client.generate(model_name, "warmup", max_tokens=1)
    
    background_tasks.add_task(pull_model)
    
    return {"message": f"Loading {model_name} in background"}


@router.get("/capture", response_model=CaptureStatus)
async def get_capture_status():
    """Get capture status from Redis state."""
    try:
        r = get_redis_client()
        now = datetime.now()
        
        # Check extension heartbeat
        ext_heartbeat = r.get(EXTENSION_HEARTBEAT_KEY)
        extension_connected = False
        if ext_heartbeat:
            heartbeat_time = datetime.fromisoformat(ext_heartbeat)
            extension_connected = (now - heartbeat_time).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS
        
        # Check OS monitor heartbeat
        os_heartbeat = r.get(OS_MONITOR_HEARTBEAT_KEY)
        os_monitor_active = False
        if os_heartbeat:
            heartbeat_time = datetime.fromisoformat(os_heartbeat)
            os_monitor_active = (now - heartbeat_time).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS
        
        # Get last event timestamp
        last_event = r.get(LAST_EVENT_KEY)
        last_event_timestamp = datetime.fromisoformat(last_event) if last_event else None
        
        # Get event counts
        events_today = int(r.get(EVENTS_TODAY_KEY) or 0)
        events_this_hour = int(r.get(EVENTS_HOUR_KEY) or 0)
        
        return CaptureStatus(
            os_monitor_active=os_monitor_active,
            browser_extension_connected=extension_connected,
            last_event_timestamp=last_event_timestamp,
            events_today=events_today,
            events_this_hour=events_this_hour
        )
    except Exception as e:
        # Fallback to defaults if Redis is unavailable
        print(f"[System] Redis error getting capture status: {e}")
        return CaptureStatus(
            os_monitor_active=False,
            browser_extension_connected=False,
            last_event_timestamp=None,
            events_today=0,
            events_this_hour=0
        )


@router.post("/capture/start")
async def start_capture():
    return {"message": "Capture started", "status": "not_implemented"}


@router.post("/capture/stop")
async def stop_capture():
    return {"message": "Capture stopped", "status": "not_implemented"}


@router.get("/logs")
async def get_recent_logs(
    level: str = "INFO",
    limit: int = 100
):
    return {
        "logs": [],
        "message": "Log retrieval not yet implemented"
    }
