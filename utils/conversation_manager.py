import uuid
import logging
from typing import Dict, List, Optional
from datetime import datetime
from .conversation_logger import conversation_logger
from .status_tracker import status_tracker

logger = logging.getLogger(__name__)

class ConversationManager:
    """Manages conversation state and logging integration"""
    
    def __init__(self):
        self.logger = conversation_logger
        logger.info("Conversation manager initialized")
    
    def create_conversation(self, user_id: str = "default") -> str:
        """Create a new conversation and return its ID"""
        conversation_id = f"{user_id}_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}"
        logger.info(f"Created new conversation: {conversation_id}")
        return conversation_id
    
    def start_analysis(self, conversation_id: str, user_query: str) -> None:
        """Start tracking analysis for a conversation"""
        status_tracker.start_analysis(conversation_id, user_query)
        logger.info(f"Started analysis tracking for conversation {conversation_id}")
    
    def update_analysis_status(self, conversation_id: str, status: str, step: int = None, 
                             data: Dict = None, error: str = None) -> None:
        """Update analysis status for a conversation"""
        status_tracker.update_status(conversation_id, status, step, data, error)
    
    def complete_analysis(self, conversation_id: str, final_data: Dict = None) -> None:
        """Mark analysis as completed"""
        status_tracker.complete_analysis(conversation_id, final_data)
    
    def get_analysis_status(self, conversation_id: str) -> Optional[Dict]:
        """Get current analysis status for a conversation"""
        return status_tracker.get_status(conversation_id)
    
    def get_analysis_status_history(self, conversation_id: str) -> List[Dict]:
        """Get analysis status history for a conversation"""
        return status_tracker.get_status_history(conversation_id)
    
    def is_analysis_active(self, conversation_id: str) -> bool:
        """Check if analysis is currently active for a conversation"""
        return status_tracker.is_analysis_active(conversation_id)
    
    def get_active_conversations(self) -> List[str]:
        """Get list of conversation IDs with active analysis"""
        return status_tracker.get_active_conversations()
    
    def load_conversation_history(self, conversation_id: str) -> List[Dict]:
        """Load conversation history for LangGraph state"""
        messages = self.logger.get_conversation_messages(conversation_id)
        logger.info(f"Loaded {len(messages)} messages for conversation {conversation_id}")
        return messages
    
    def prepare_processing_metadata(self, state: Dict) -> Dict:
        """Prepare metadata for logging the processing pipeline"""
        metadata = {
            "timestamp": datetime.now().isoformat(),
            "iteration_count": state.get("iteration_count", 0),
            "thinking_result": {
                "needs_web_search": state.get("thinking_result", {}).get("needs_web_search", False),
                "search_queries_count": len(state.get("thinking_result", {}).get("search_queries", [])),
                "elaborated_intent": state.get("thinking_result", {}).get("elaborated_intent", "")
            },
            "search_results": {
                "raw_docs_count": len(state.get("raw_docs", [])),
                "distilled_docs_count": len(state.get("distiller_result", {}).get("distilled_docs", [])),
                "filtered_out_count": state.get("distiller_result", {}).get("filtered_out_count", 0)
            },
            "qa_evaluation": {
                "quality_score": state.get("qa_result", {}).get("quality_score", 0.0),
                "needs_more_data": state.get("qa_result", {}).get("needs_more_data", False),
                "should_reformat": state.get("qa_result", {}).get("should_reformat", False)
            },
            "response_metrics": {
                "answer_length": len(state.get("answer", "")),
                "citations_count": len(state.get("citations", [])),
                "processing_time_seconds": self._calculate_processing_time(state)
            }
        }
        
        return metadata
    
    def _calculate_processing_time(self, state: Dict) -> float:
        """Calculate processing time if available in diagnostics"""
        diagnostics = state.get("diagnostics", {})
        start_time = diagnostics.get("start_time")
        
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time)
                return (datetime.now() - start_dt).total_seconds()
            except:
                pass
        
        return 0.0
    
    def log_conversation_turn(self, conversation_id: str, user_query: str, 
                            assistant_response: str, citations: List[str], 
                            processing_metadata: Dict, conversation_title: str = None) -> None:
        """Log a complete conversation turn"""
        # Log user message
        self.logger.log_user_message(
            conversation_id=conversation_id,
            message=user_query,
            metadata={"query_length": len(user_query)}
        )
        
        # Log assistant response
        self.logger.log_assistant_response(
            conversation_id=conversation_id,
            response=assistant_response,
            citations=citations,
            processing_metadata=processing_metadata
        )
        
        # Update conversation title if provided
        if conversation_title:
            self.logger.update_conversation_title(conversation_id, conversation_title)
        
        logger.info(f"Logged complete conversation turn for {conversation_id}")
    
    def get_conversation_summary(self, conversation_id: str) -> Optional[Dict]:
        """Get a summary of a conversation"""
        return self.logger.get_conversation_stats(conversation_id)
    
    def list_user_conversations(self, user_id: str = "default", limit: int = 20) -> List[Dict]:
        """List conversations for a specific user"""
        all_conversations = self.logger.list_conversations(limit=limit * 2)
        user_conversations = [
            conv for conv in all_conversations 
            if conv["conversation_id"].startswith(f"{user_id}_")
        ]
        return user_conversations[:limit]
    
    def list_all_conversations(self, limit: int = 50) -> List[Dict]:
        """List all conversations regardless of user ID"""
        return self.logger.list_conversations(limit=limit)
    
    def continue_conversation(self, conversation_id: str) -> Optional[Dict]:
        """Prepare state for continuing an existing conversation"""
        conversation = self.logger.get_conversation(conversation_id)
        
        if not conversation:
            logger.warning(f"Conversation {conversation_id} not found")
            return None
        
        # Extract messages for LangGraph state
        messages = conversation["messages"]
        
        # Prepare state for continuation
        state = {
            "conversation_id": conversation_id,
            "messages": messages,
            "processing_metadata": {},
            "iteration_count": 0
        }
        
        logger.info(f"Prepared continuation for conversation {conversation_id} with {len(messages)} messages")
        return state
    
    def get_conversation(self, conversation_id: str) -> Optional[Dict]:
        """Get a conversation by ID"""
        return self.logger.get_conversation(conversation_id)
    
    def get_conversation_messages(self, conversation_id: str) -> List[Dict]:
        """Get just the messages from a conversation"""
        return self.logger.get_conversation_messages(conversation_id)
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation"""
        return self.logger.delete_conversation(conversation_id)

# Global instance
conversation_manager = ConversationManager()
