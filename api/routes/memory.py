from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

router = APIRouter()


class MemoryCategory(str, Enum):
    WORK = "work"
    CODE = "code"
    RESEARCH = "research"
    STUDYING = "studying"
    MEETINGS = "meetings"
    ENTERTAINMENT = "entertainment"
    SHOPPING = "shopping"
    HEALTH = "health"
    TRAVEL = "travel"
    FINANCE = "finance"
    SOCIAL = "social"
    CREATIVE = "creative"
    PERSONAL = "personal"
    UNCATEGORIZED = "uncategorized"


class MemorySource(str, Enum):
    BROWSER = "browser"
    FILE_SYSTEM = "file_system"
    CLIPBOARD = "clipboard"
    SCREENSHOT = "screenshot"
    MANUAL = "manual"


class MemoryBase(BaseModel):
    raw_text: str
    summary: Optional[str] = None
    category: MemoryCategory
    source: MemorySource
    source_url: Optional[str] = None
    source_path: Optional[str] = None
    tags: List[str] = []
    image_base64: Optional[str] = None  # Screenshot data if captured


class MemoryCreate(MemoryBase):
    pass


class Memory(MemoryBase):
    memory_id: str
    created_at: datetime
    updated_at: datetime
    embedding_id: Optional[str] = None
    
    class Config:
        from_attributes = True


class MemorySearchRequest(BaseModel):
    query: str
    category: Optional[MemoryCategory] = None
    source: Optional[MemorySource] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class MemorySearchResponse(BaseModel):
    memories: List[Memory]
    total_count: int
    query_time_ms: int


class EntityNode(BaseModel):
    entity_id: str
    name: str
    entity_type: str
    properties: dict = {}


class Relationship(BaseModel):
    from_entity: str
    to_entity: str
    relationship_type: str
    properties: dict = {}


class GraphQueryRequest(BaseModel):
    start_entity: str
    relationship_type: Optional[str] = None
    direction: str = "both"
    depth: int = Field(default=2, ge=1, le=4)


class GraphQueryResponse(BaseModel):
    entities: List[EntityNode]
    relationships: List[Relationship]
    paths: List[List[str]]


@router.get("/", response_model=List[Memory])
def list_memories(
    category: Optional[MemoryCategory] = None,
    source: Optional[MemorySource] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at", pattern="^(created_at|updated_at)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$")
):
    from memory.vector_store import VectorStore
    
    store = VectorStore()
    filters = {}
    if category:
        filters["category"] = category.value
    if source:
        filters["source"] = source.value
    
    memory_objects = store.list(
        filters=filters,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    valid_categories = {c.value for c in MemoryCategory}
    valid_sources = {s.value for s in MemorySource}
    
    results = []
    for m in memory_objects:
        cat = m.category if m.category in valid_categories else "uncategorized"
        src = m.source if m.source in valid_sources else "manual"
        results.append(Memory(
            memory_id=m.memory_id,
            raw_text=m.raw_text,
            summary=m.summary,
            category=cat,
            source=src,
            source_url=m.source_url,
            source_path=m.source_path,
            tags=m.tags,
            created_at=m.created_at,
            updated_at=m.updated_at,
            embedding_id=m.embedding_id,
            image_base64=getattr(m, 'image_base64', None)
        ))
    
    return results


@router.get("/{memory_id}", response_model=Memory)
def get_memory(memory_id: str):
    from memory.vector_store import VectorStore
    
    store = VectorStore()
    m = store.get_by_id(memory_id)
    
    if not m:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    valid_categories = {c.value for c in MemoryCategory}
    valid_sources = {s.value for s in MemorySource}
    cat = m.category if m.category in valid_categories else "uncategorized"
    src = m.source if m.source in valid_sources else "manual"
    
    return Memory(
        memory_id=m.memory_id,
        raw_text=m.raw_text,
        summary=m.summary,
        category=cat,
        source=src,
        source_url=m.source_url,
        source_path=m.source_path,
        tags=m.tags,
        created_at=m.created_at,
        updated_at=m.updated_at,
        embedding_id=m.embedding_id,
        image_base64=getattr(m, 'image_base64', None)
    )


@router.post("/", response_model=Memory, status_code=201)
async def create_memory(memory: MemoryCreate):
    from memory.vector_store import VectorStore
    
    store = VectorStore()
    
    m = await store.add(
        raw_text=memory.raw_text,
        summary=memory.summary,
        category=memory.category.value,
        source=memory.source.value,
        source_url=memory.source_url,
        source_path=memory.source_path,
        tags=memory.tags
    )
    
    return Memory(
        memory_id=m.memory_id,
        raw_text=m.raw_text,
        summary=m.summary,
        category=memory.category,
        source=memory.source,
        source_url=m.source_url,
        source_path=m.source_path,
        tags=m.tags,
        created_at=m.created_at,
        updated_at=m.updated_at,
        embedding_id=m.embedding_id
    )


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: str):
    from memory.vector_store import VectorStore
    
    store = VectorStore()
    store.delete(memory_id)


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(request: MemorySearchRequest):
    from memory.vector_store import VectorStore
    
    start = datetime.now()
    store = VectorStore()
    
    results = await store.search(
        query=request.query,
        category=request.category.value if request.category else None,
        source=request.source.value if request.source else None,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit
    )
    
    query_time = (datetime.now() - start).total_seconds() * 1000
    
    valid_categories = {c.value for c in MemoryCategory}
    valid_sources = {s.value for s in MemorySource}
    
    memories = []
    for sr in results:
        m = sr.memory
        cat = m.category if m.category in valid_categories else "uncategorized"
        src = m.source if m.source in valid_sources else "manual"
        memories.append(Memory(
            memory_id=m.memory_id,
            raw_text=m.raw_text,
            summary=m.summary,
            category=cat,
            source=src,
            source_url=m.source_url,
            source_path=m.source_path,
            tags=m.tags,
            created_at=m.created_at,
            updated_at=m.updated_at,
            embedding_id=m.embedding_id,
            image_base64=getattr(m, 'image_base64', None)
        ))
    
    return MemorySearchResponse(
        memories=memories,
        total_count=len(memories),
        query_time_ms=int(query_time)
    )


@router.post("/graph/query", response_model=GraphQueryResponse)
def query_graph(request: GraphQueryRequest):
    from memory.knowledge_graph import KnowledgeGraph
    
    graph = KnowledgeGraph()
    result = graph.traverse(
        start_entity=request.start_entity,
        relationship_type=request.relationship_type,
        direction=request.direction,
        depth=request.depth
    )
    
    return GraphQueryResponse(
        entities=result.get("entities", []),
        relationships=result.get("relationships", []),
        paths=result.get("paths", [])
    )


@router.get("/graph/entity/{entity_name}", response_model=EntityNode)
def get_entity(entity_name: str):
    from memory.knowledge_graph import KnowledgeGraph
    
    graph = KnowledgeGraph()
    entity = graph.get_entity(entity_name)
    
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    return EntityNode(**entity)


@router.get("/stats/categories")
def get_category_stats():
    from memory.vector_store import VectorStore
    
    store = VectorStore()
    return store.get_category_stats()


@router.get("/stats/timeline")
def get_timeline_stats(
    days: int = Query(default=30, ge=1, le=365)
):
    from memory.vector_store import VectorStore
    
    store = VectorStore()
    return store.get_timeline_stats(days=days)
