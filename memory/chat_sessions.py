"""
Chat Session Storage - Stores chat conversations for later retrieval.
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Storage directory for chat sessions
CHAT_STORAGE_DIR = Path(os.getenv("CHAT_STORAGE_DIR", "./bmo_data/chat_sessions"))


@dataclass
class ChatMessage:
    """A single chat message."""
    id: str
    sender: str  # 'user' or 'bmo'
    text: str
    timestamp: str
    confidence: Optional[float] = None
    processing_time_ms: Optional[int] = None
    screenshots: Optional[List[Dict[str, Any]]] = None


@dataclass
class ChatSession:
    """A chat session containing multiple messages."""
    session_id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[ChatMessage]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [asdict(m) for m in self.messages]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatSession":
        messages = [ChatMessage(**m) for m in data.get("messages", [])]
        return cls(
            session_id=data["session_id"],
            title=data["title"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            messages=messages
        )


class ChatSessionStore:
    """File-based chat session storage."""
    
    def __init__(self):
        """Initialize the store and ensure storage directory exists."""
        CHAT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Chat session storage initialized at {CHAT_STORAGE_DIR}")
    
    def _get_session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        return CHAT_STORAGE_DIR / f"{session_id}.json"
    
    def create_session(self, title: Optional[str] = None) -> ChatSession:
        """Create a new chat session."""
        session_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()
        
        session = ChatSession(
            session_id=session_id,
            title=title or f"Chat {datetime.now().strftime('%b %d, %H:%M')}",
            created_at=now,
            updated_at=now,
            messages=[]
        )
        
        self._save_session(session)
        logger.info(f"Created new chat session: {session_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Get a session by ID."""
        path = self._get_session_path(session_id)
        if not path.exists():
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ChatSession.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None
    
    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all sessions with metadata (without full messages)."""
        sessions = []
        
        for path in sorted(CHAT_STORAGE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Return summary without full message content
                sessions.append({
                    "session_id": data["session_id"],
                    "title": data["title"],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "message_count": len(data.get("messages", [])),
                    "preview": data["messages"][-1]["text"][:100] if data.get("messages") else ""
                })
                
                if len(sessions) >= limit:
                    break
            except Exception as e:
                logger.warning(f"Failed to read session file {path}: {e}")
        
        return sessions
    
    def add_message(
        self,
        session_id: str,
        sender: str,
        text: str,
        confidence: Optional[float] = None,
        processing_time_ms: Optional[int] = None,
        screenshots: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[ChatMessage]:
        """Add a message to a session."""
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"Session not found: {session_id}")
            return None
        
        message = ChatMessage(
            id=str(uuid.uuid4())[:8],
            sender=sender,
            text=text,
            timestamp=datetime.utcnow().isoformat(),
            confidence=confidence,
            processing_time_ms=processing_time_ms,
            screenshots=screenshots
        )
        
        session.messages.append(message)
        session.updated_at = datetime.utcnow().isoformat()
        
        # Auto-update title from first user message if still default
        if sender == 'user' and len(session.messages) == 1:
            session.title = text[:50] + ("..." if len(text) > 50 else "")
        
        self._save_session(session)
        return message
    
    def update_session_title(self, session_id: str, title: str) -> bool:
        """Update session title."""
        session = self.get_session(session_id)
        if not session:
            return False
        
        session.title = title
        session.updated_at = datetime.utcnow().isoformat()
        self._save_session(session)
        return True
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        path = self._get_session_path(session_id)
        if path.exists():
            path.unlink()
            logger.info(f"Deleted session: {session_id}")
            return True
        return False
    
    def _save_session(self, session: ChatSession):
        """Save session to file."""
        path = self._get_session_path(session.session_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)


# Global store instance
_store: Optional[ChatSessionStore] = None


def get_chat_store() -> ChatSessionStore:
    """Get or create the global chat session store."""
    global _store
    if _store is None:
        _store = ChatSessionStore()
    return _store
