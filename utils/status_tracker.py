import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from threading import Lock

logger = logging.getLogger(__name__)

class AnalysisStatusTracker:
    """Tracks the status of ongoing analysis sessions for persistence across conversation switches."""
    
    def __init__(self, status_dir: str = "analysis_status"):
        self.status_dir = status_dir
        self.lock = Lock()
        os.makedirs(status_dir, exist_ok=True)
        
    def _get_status_file_path(self, conversation_id: str) -> str:
        """Get the file path for a conversation's status."""
        return os.path.join(self.status_dir, f"{conversation_id}_status.json")
    
    def start_analysis(self, conversation_id: str, user_query: str) -> None:
        """Start tracking analysis for a conversation."""
        with self.lock:
            status = {
                "conversation_id": conversation_id,
                "user_query": user_query,
                "status": "thinking",
                "current_step": 1,
                "total_steps": 6,
                "started_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "steps_completed": [],
                "current_data": {},
                "is_active": True,
                "error": None,
                "status_history": []  # Store history of status updates
            }
            self._save_status(conversation_id, status)
            logger.info(f"Started analysis tracking for conversation {conversation_id}")
    
    def update_status(self, conversation_id: str, status: str, step: int = None, 
                     data: Dict[str, Any] = None, error: str = None) -> None:
        """Update the analysis status for a conversation."""
        with self.lock:
            current_status = self._load_status(conversation_id)
            if not current_status:
                logger.warning(f"No status found for conversation {conversation_id}")
                return
                
            current_status["status"] = status
            current_status["last_updated"] = datetime.now().isoformat()
            
            if step is not None:
                current_status["current_step"] = step
                
            if data is not None:
                current_status["current_data"].update(data)
                
            if error is not None:
                current_status["error"] = error
                current_status["is_active"] = False
                
            # Mark step as completed
            if step is not None and step not in current_status["steps_completed"]:
                current_status["steps_completed"].append(step)
            
            # Add to status history
            status_entry = {
                "status": status,
                "step": step,
                "data": data or {},
                "timestamp": datetime.now().isoformat()
            }
            current_status["status_history"].append(status_entry)
            
            # Keep only last 20 status updates to avoid file bloat
            if len(current_status["status_history"]) > 20:
                current_status["status_history"] = current_status["status_history"][-20:]
                
            self._save_status(conversation_id, current_status)
            logger.debug(f"Updated status for {conversation_id}: {status} (step {step})")
    
    def complete_analysis(self, conversation_id: str, final_data: Dict[str, Any] = None) -> None:
        """Mark analysis as completed."""
        with self.lock:
            current_status = self._load_status(conversation_id)
            if not current_status:
                return
                
            current_status["status"] = "complete"
            current_status["current_step"] = current_status["total_steps"]
            current_status["last_updated"] = datetime.now().isoformat()
            current_status["is_active"] = False
            current_status["completed_at"] = datetime.now().isoformat()
            
            if final_data:
                current_status["current_data"].update(final_data)
                
            self._save_status(conversation_id, current_status)
            logger.info(f"Completed analysis tracking for conversation {conversation_id}")
    
    def get_status(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get the current status of a conversation's analysis."""
        with self.lock:
            return self._load_status(conversation_id)
    
    def get_status_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Get the status history for a conversation's analysis."""
        with self.lock:
            status = self._load_status(conversation_id)
            return status.get("status_history", []) if status else []
    
    def is_analysis_active(self, conversation_id: str) -> bool:
        """Check if analysis is currently active for a conversation."""
        status = self.get_status(conversation_id)
        return status and status.get("is_active", False)
    
    def get_active_conversations(self) -> List[str]:
        """Get list of conversation IDs with active analysis."""
        with self.lock:
            active_conversations = []
            for filename in os.listdir(self.status_dir):
                if filename.endswith("_status.json"):
                    conversation_id = filename.replace("_status.json", "")
                    status = self._load_status(conversation_id)
                    if status and status.get("is_active", False):
                        active_conversations.append(conversation_id)
            return active_conversations
    
    def cleanup_old_status(self, max_age_hours: int = 24) -> None:
        """Clean up status files older than specified hours."""
        with self.lock:
            cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)
            cleaned = 0
            
            for filename in os.listdir(self.status_dir):
                if filename.endswith("_status.json"):
                    file_path = os.path.join(self.status_dir, filename)
                    if os.path.getmtime(file_path) < cutoff_time:
                        os.remove(file_path)
                        cleaned += 1
                        
            if cleaned > 0:
                logger.info(f"Cleaned up {cleaned} old status files")
    
    def _load_status(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Load status from file."""
        file_path = self._get_status_file_path(conversation_id)
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load status for {conversation_id}: {e}")
        return None
    
    def _save_status(self, conversation_id: str, status: Dict[str, Any]) -> None:
        """Save status to file."""
        file_path = self._get_status_file_path(conversation_id)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save status for {conversation_id}: {e}")
    
    def delete_status(self, conversation_id: str) -> None:
        """Delete status file for a conversation."""
        with self.lock:
            file_path = self._get_status_file_path(conversation_id)
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Deleted status file for conversation {conversation_id}")
            except Exception as e:
                logger.error(f"Failed to delete status file for {conversation_id}: {e}")

# Global instance
status_tracker = AnalysisStatusTracker()
