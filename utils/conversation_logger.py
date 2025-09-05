import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class ConversationLogger:
    """Handles conversation logging and retrieval for frontend support"""
    
    def __init__(self, conversations_dir: str = "conversations"):
        self.conversations_dir = Path(conversations_dir)
        self.conversations_dir.mkdir(exist_ok=True)
        logger.info(f"Conversation logger initialized with directory: {self.conversations_dir}")
    
    def _get_conversation_file(self, conversation_id: str) -> Path:
        """Get the file path for a conversation"""
        return self.conversations_dir / f"{conversation_id}.json"
    
    def _load_conversation(self, conversation_id: str) -> Dict:
        """Load a conversation from file"""
        conversation_file = self._get_conversation_file(conversation_id)
        
        if not conversation_file.exists():
            return {
                "conversation_id": conversation_id,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "title": None,
                "messages": [],
                "metadata": {
                    "total_messages": 0,
                    "total_queries": 0,
                    "total_responses": 0
                }
            }
        
        try:
            with open(conversation_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load conversation {conversation_id}: {e}")
            return self._load_conversation(conversation_id)  # Return fresh conversation
    
    def _save_conversation(self, conversation: Dict) -> None:
        """Save a conversation to file"""
        conversation_file = self._get_conversation_file(conversation["conversation_id"])
        
        try:
            with open(conversation_file, 'w', encoding='utf-8') as f:
                json.dump(conversation, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved conversation {conversation['conversation_id']}")
        except Exception as e:
            logger.error(f"Failed to save conversation {conversation['conversation_id']}: {e}")
    
    def log_user_message(self, conversation_id: str, message: str, metadata: Optional[Dict] = None) -> Dict:
        """Log a user message"""
        conversation = self._load_conversation(conversation_id)
        
        user_message = {
            "role": "user",
            "content": message,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        conversation["messages"].append(user_message)
        conversation["updated_at"] = datetime.now().isoformat()
        conversation["metadata"]["total_messages"] += 1
        conversation["metadata"]["total_queries"] += 1
        
        self._save_conversation(conversation)
        logger.info(f"Logged user message in conversation {conversation_id}")
        return conversation
    
    def log_assistant_response(self, conversation_id: str, response: str, 
                             citations: List[str] = None, 
                             processing_metadata: Optional[Dict] = None) -> Dict:
        """Log an assistant response with metadata"""
        conversation = self._load_conversation(conversation_id)
        
        assistant_message = {
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().isoformat(),
            "citations": citations or [],
            "metadata": {
                "citations_count": len(citations) if citations else 0,
                "response_length": len(response),
                "processing_metadata": processing_metadata or {}
            }
        }
        
        conversation["messages"].append(assistant_message)
        conversation["updated_at"] = datetime.now().isoformat()
        conversation["metadata"]["total_messages"] += 1
        conversation["metadata"]["total_responses"] += 1
        
        self._save_conversation(conversation)
        logger.info(f"Logged assistant response in conversation {conversation_id}")
        return conversation
    
    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """Update the title of a conversation"""
        conversation = self._load_conversation(conversation_id)
        if not conversation:
            return False
        
        conversation["title"] = title
        conversation["updated_at"] = datetime.now().isoformat()
        
        self._save_conversation(conversation)
        logger.info(f"Updated title for conversation {conversation_id}: '{title}'")
        return True
    
    def get_conversation(self, conversation_id: str) -> Optional[Dict]:
        """Get a conversation by ID"""
        conversation_file = self._get_conversation_file(conversation_id)
        
        if not conversation_file.exists():
            return None
        
        return self._load_conversation(conversation_id)
    
    def get_conversation_messages(self, conversation_id: str) -> List[Dict]:
        """Get just the messages from a conversation"""
        conversation = self.get_conversation(conversation_id)
        return conversation["messages"] if conversation else []
    
    def list_conversations(self, limit: int = 50) -> List[Dict]:
        """List all conversations with metadata"""
        conversations = []
        
        for conversation_file in self.conversations_dir.glob("*.json"):
            try:
                conversation = self._load_conversation(conversation_file.stem)
                conversations.append({
                    "conversation_id": conversation["conversation_id"],
                    "created_at": conversation["created_at"],
                    "updated_at": conversation["updated_at"],
                    "title": conversation.get("title"),
                    "message_count": conversation["metadata"]["total_messages"],
                    "last_message_preview": conversation["messages"][-1]["content"][:100] + "..." 
                        if conversation["messages"] else "No messages"
                })
            except Exception as e:
                logger.error(f"Failed to load conversation {conversation_file.stem}: {e}")
                continue
        
        # Sort by updated_at descending
        conversations.sort(key=lambda x: x["updated_at"], reverse=True)
        return conversations[:limit]
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation"""
        conversation_file = self._get_conversation_file(conversation_id)
        
        try:
            if conversation_file.exists():
                conversation_file.unlink()
                logger.info(f"Deleted conversation {conversation_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete conversation {conversation_id}: {e}")
            return False
    
    def get_conversation_stats(self, conversation_id: str) -> Optional[Dict]:
        """Get statistics for a conversation"""
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return None
        
        messages = conversation["messages"]
        user_messages = [m for m in messages if m["role"] == "user"]
        assistant_messages = [m for m in messages if m["role"] == "assistant"]
        
        total_citations = sum(
            m.get("metadata", {}).get("citations_count", 0) 
            for m in assistant_messages
        )
        
        avg_response_length = sum(
            m.get("metadata", {}).get("response_length", 0) 
            for m in assistant_messages
        ) / len(assistant_messages) if assistant_messages else 0
        
        return {
            "conversation_id": conversation_id,
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
            "total_messages": len(messages),
            "user_messages": len(user_messages),
            "assistant_messages": len(assistant_messages),
            "total_citations": total_citations,
            "avg_response_length": round(avg_response_length, 2),
            "duration_minutes": self._calculate_duration(conversation)
        }
    
    def _calculate_duration(self, conversation: Dict) -> float:
        """Calculate conversation duration in minutes"""
        try:
            if not conversation["messages"]:
                return 0.0
            
            first_message = conversation["messages"][0]
            last_message = conversation["messages"][-1]
            
            start_time = datetime.fromisoformat(first_message["timestamp"])
            end_time = datetime.fromisoformat(last_message["timestamp"])
            
            duration = (end_time - start_time).total_seconds() / 60
            return round(duration, 2)
        except Exception as e:
            logger.error(f"Failed to calculate duration: {e}")
            return 0.0

# Global instance
conversation_logger = ConversationLogger()
