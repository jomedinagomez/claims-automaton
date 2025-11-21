"""Session persistence for claims orchestration workflows."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from semantic_kernel.contents import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.utils.author_role import AuthorRole

logger = logging.getLogger(__name__)


class SessionStore:
    """
    Persistent storage for claims orchestration sessions.
    
    Manages:
    - Chat history serialization/deserialization
    - Context metadata snapshots
    - Session lifecycle (create, load, save, archive)
    - Resume capability for paused claims
    
    Storage format:
    - sessions/{claim_id}/session.json: Full session state
    - sessions/{claim_id}/context.json: Current context snapshot
    - sessions/{claim_id}/history.jsonl: Chat history (one message per line)
    """
    
    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize session store.
        
        Args:
            base_dir: Root directory for session storage (default: ./sessions)
        """
        self.base_dir = Path(base_dir) if base_dir else Path("sessions")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("SessionStore initialized at: %s", self.base_dir)
    
    def save_session(
        self,
        claim_id: str,
        chat_history: ChatHistory,
        context: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Save complete session state to disk.
        
        Args:
            claim_id: Unique claim identifier
            chat_history: Current conversation history
            context: Orchestration context metadata
            metadata: Additional session metadata (timestamps, status, etc.)
        
        Returns:
            Path to session directory
        """
        session_dir = self.base_dir / claim_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Save context snapshot
        context_path = session_dir / "context.json"
        with context_path.open("w", encoding="utf-8") as f:
            json.dump(context, f, indent=2, default=str)
        
        # Save chat history as JSONL (one message per line)
        history_path = session_dir / "history.jsonl"
        with history_path.open("w", encoding="utf-8") as f:
            for message in chat_history.messages:
                message_dict = self._serialize_message(message)
                f.write(json.dumps(message_dict, default=str) + "\n")
        
        # Save session metadata
        session_metadata = {
            "claim_id": claim_id,
            "saved_at": datetime.utcnow().isoformat() + "Z",
            "message_count": len(chat_history.messages),
            "status": context.get("state", "unknown"),
            "missing_documents": context.get("missing_documents", []),
        }
        
        if metadata:
            session_metadata.update(metadata)
        
        session_path = session_dir / "session.json"
        with session_path.open("w", encoding="utf-8") as f:
            json.dump(session_metadata, f, indent=2, default=str)
        
        logger.info(
            "Session saved: claim_id=%s, messages=%d, status=%s",
            claim_id,
            len(chat_history.messages),
            session_metadata["status"],
        )
        
        return session_dir
    
    def load_session(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """
        Load complete session state from disk.
        
        Args:
            claim_id: Unique claim identifier
        
        Returns:
            Dictionary with keys:
                - chat_history: Restored ChatHistory instance
                - context: Orchestration context metadata
                - metadata: Session metadata (timestamps, status, etc.)
            Returns None if session not found
        """
        session_dir = self.base_dir / claim_id
        
        if not session_dir.exists():
            logger.warning("Session not found: %s", claim_id)
            return None
        
        # Load session metadata
        session_path = session_dir / "session.json"
        if not session_path.exists():
            logger.error("Session metadata missing: %s", claim_id)
            return None
        
        with session_path.open("r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        # Load context
        context_path = session_dir / "context.json"
        context = {}
        if context_path.exists():
            with context_path.open("r", encoding="utf-8") as f:
                context = json.load(f)
        
        # Load chat history
        history_path = session_dir / "history.jsonl"
        chat_history = ChatHistory()
        
        if history_path.exists():
            with history_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        message_dict = json.loads(line)
                        message = self._deserialize_message(message_dict)
                        chat_history.add_message(message)
        
        logger.info(
            "Session loaded: claim_id=%s, messages=%d, status=%s",
            claim_id,
            len(chat_history.messages),
            metadata.get("status", "unknown"),
        )
        
        return {
            "chat_history": chat_history,
            "context": context,
            "metadata": metadata,
        }
    
    def session_exists(self, claim_id: str) -> bool:
        """
        Check if session exists for given claim ID.
        
        Args:
            claim_id: Unique claim identifier
        
        Returns:
            True if session directory and metadata exist
        """
        session_dir = self.base_dir / claim_id
        return session_dir.exists() and (session_dir / "session.json").exists()
    
    def list_sessions(self) -> list[str]:
        """
        List all stored session claim IDs.
        
        Returns:
            List of claim IDs with persisted sessions
        """
        if not self.base_dir.exists():
            return []
        
        sessions = []
        for item in self.base_dir.iterdir():
            if item.is_dir() and (item / "session.json").exists():
                sessions.append(item.name)
        
        return sorted(sessions)
    
    def archive_session(self, claim_id: str) -> Optional[Path]:
        """
        Archive completed session by adding completion timestamp.
        
        Args:
            claim_id: Unique claim identifier
        
        Returns:
            Path to archived session directory, or None if not found
        """
        session_dir = self.base_dir / claim_id
        
        if not session_dir.exists():
            logger.warning("Cannot archive non-existent session: %s", claim_id)
            return None
        
        session_path = session_dir / "session.json"
        if session_path.exists():
            with session_path.open("r", encoding="utf-8") as f:
                metadata = json.load(f)
            
            metadata["archived_at"] = datetime.utcnow().isoformat() + "Z"
            
            with session_path.open("w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, default=str)
        
        logger.info("Session archived: %s", claim_id)
        return session_dir
    
    @staticmethod
    def _serialize_message(message: ChatMessageContent) -> Dict[str, Any]:
        """
        Serialize ChatMessageContent to JSON-compatible dictionary.
        
        Args:
            message: Semantic Kernel message object
        
        Returns:
            Dictionary with role, content, metadata
        """
        return {
            "role": str(message.role.value if hasattr(message.role, "value") else message.role),
            "content": str(message.content) if message.content else "",
            "name": getattr(message, "name", None),
            "metadata": getattr(message, "metadata", {}),
        }
    
    @staticmethod
    def _deserialize_message(message_dict: Dict[str, Any]) -> ChatMessageContent:
        """
        Deserialize dictionary to ChatMessageContent.
        
        Args:
            message_dict: Dictionary with role, content, metadata
        
        Returns:
            Restored ChatMessageContent instance
        """
        role_str = message_dict.get("role", "user").lower()
        role_map = {
            "user": AuthorRole.USER,
            "assistant": AuthorRole.ASSISTANT,
            "system": AuthorRole.SYSTEM,
            "tool": AuthorRole.TOOL,
        }
        role = role_map.get(role_str, AuthorRole.USER)
        
        return ChatMessageContent(
            role=role,
            content=message_dict.get("content", ""),
            name=message_dict.get("name"),
            metadata=message_dict.get("metadata", {}),
        )
