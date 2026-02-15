from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

router = APIRouter()


class SessionCreateRequest(BaseModel):
    title: Optional[str] = None


class SessionUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class MessageAddRequest(BaseModel):
    sender: str = Field(..., pattern="^(user|bmo)$")
    text: str = Field(..., min_length=1)
    confidence: Optional[float] = None
    processing_time_ms: Optional[int] = None
    screenshots: Optional[List[Dict[str, Any]]] = None


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    preview: str


class SessionMessage(BaseModel):
    id: str
    sender: str
    text: str
    timestamp: str
    confidence: Optional[float] = None
    processing_time_ms: Optional[int] = None
    screenshots: Optional[List[Dict[str, Any]]] = None


class SessionDetail(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[SessionMessage]


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    category_filter: Optional[str] = None  # Single category (legacy)
    categories: Optional[List[str]] = None  # Multiple categories (new)
    time_range_days: Optional[int] = Field(None, ge=1, le=365)
    fast_mode: bool = Field(default=True, description="Skip verification for faster response")


class SourceReference(BaseModel):
    memory_id: str
    summary: str
    timestamp: datetime
    source: str
    category: str
    relevance_score: float


class ScreenshotRef(BaseModel):
    memory_id: str
    image_base64: str
    timestamp: Optional[datetime] = None
    source_url: Optional[str] = None
    category: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    sources: List[SourceReference]
    screenshots: List[ScreenshotRef] = []
    processing_time_ms: int
    intent_detected: str
    uncertain: bool = False


class StreamChunk(BaseModel):
    type: str
    content: Optional[str] = None
    metadata: Optional[dict] = None


@router.post("/query", response_model=ChatResponse)
async def chat_query(request: ChatRequest):
    from agents.orchestrator import AgentOrchestrator
    
    category_filter = request.category_filter
    if request.categories and len(request.categories) > 0:
        category_filter = request.categories[0] if len(request.categories) == 1 else None
    
    orchestrator = AgentOrchestrator()
    result = await orchestrator.process_query(
        query=request.query,
        category_filter=category_filter,
        category_filters=request.categories,
        time_range_days=request.time_range_days,
        skip_verification=request.fast_mode
    )
    
    sources = []
    for s in result.sources:
        sources.append(SourceReference(
            memory_id=s.get("memory_id", ""),
            summary=s.get("summary", ""),
            timestamp=s.get("timestamp", datetime.now()),
            source=s.get("source", ""),
            category=s.get("category", ""),
            relevance_score=s.get("relevance_score", 0.0)
        ))
    
    screenshots = []
    for sc in result.screenshots:
        if sc.get("image_base64"):
            screenshots.append(ScreenshotRef(
                memory_id=sc.get("memory_id", ""),
                image_base64=sc.get("image_base64", ""),
                timestamp=sc.get("timestamp"),
                source_url=sc.get("source_url"),
                category=sc.get("category")
            ))
    
    return ChatResponse(
        answer=result.answer,
        confidence=result.confidence,
        sources=sources,
        screenshots=screenshots,
        processing_time_ms=result.processing_time_ms,
        intent_detected=result.intent_detected,
        uncertain=result.confidence < 0.7
    )


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("query", "")
            
            await websocket.send_json({"type": "status", "content": "routing"})
            
            from agents.orchestrator import AgentOrchestrator
            orchestrator = AgentOrchestrator()
            result = await orchestrator.process_query(query)
            
            for source in result.sources:
                await websocket.send_json({
                    "type": "source",
                    "metadata": source
                })
            
            await websocket.send_json({
                "type": "complete",
                "content": result.answer,
                "metadata": {
                    "confidence": result.confidence,
                    "processing_time_ms": result.processing_time_ms,
                    "intent": result.intent_detected
                }
            })
    
    except WebSocketDisconnect:
        pass


@router.get("/sessions", response_model=List[SessionSummary])
def list_sessions(limit: int = 50):
    from memory.chat_sessions import get_chat_store
    store = get_chat_store()
    sessions = store.list_sessions(limit=limit)
    return [SessionSummary(**s) for s in sessions]


@router.post("/sessions", response_model=SessionDetail, status_code=201)
def create_session(request: SessionCreateRequest):
    from memory.chat_sessions import get_chat_store
    store = get_chat_store()
    session = store.create_session(title=request.title)
    return SessionDetail(
        session_id=session.session_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[]
    )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str):
    from memory.chat_sessions import get_chat_store
    store = get_chat_store()
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    messages = [
        SessionMessage(
            id=m.id,
            sender=m.sender,
            text=m.text,
            timestamp=m.timestamp,
            confidence=m.confidence,
            processing_time_ms=m.processing_time_ms,
            screenshots=m.screenshots
        )
        for m in session.messages
    ]
    
    return SessionDetail(
        session_id=session.session_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=messages
    )


@router.put("/sessions/{session_id}", response_model=SessionDetail)
def update_session(session_id: str, request: SessionUpdateRequest):
    from memory.chat_sessions import get_chat_store
    store = get_chat_store()
    
    if not store.update_session_title(session_id, request.title):
        raise HTTPException(status_code=404, detail="Session not found")
    
    return get_session(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    from memory.chat_sessions import get_chat_store
    store = get_chat_store()
    if not store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/sessions/{session_id}/messages", response_model=SessionMessage, status_code=201)
def add_message(session_id: str, request: MessageAddRequest):
    from memory.chat_sessions import get_chat_store
    store = get_chat_store()
    
    message = store.add_message(
        session_id=session_id,
        sender=request.sender,
        text=request.text,
        confidence=request.confidence,
        processing_time_ms=request.processing_time_ms,
        screenshots=request.screenshots
    )
    
    if not message:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return SessionMessage(
        id=message.id,
        sender=message.sender,
        text=message.text,
        timestamp=message.timestamp,
        confidence=message.confidence,
        processing_time_ms=message.processing_time_ms,
        screenshots=message.screenshots
    )
