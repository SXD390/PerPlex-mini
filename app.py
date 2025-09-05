import os
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables before any other imports
load_dotenv()
os.environ.setdefault("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY",""))

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('perplex-lite.log')
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"Logging configured at {log_level} level")

from graph import build_app
from utils.conversation_manager import conversation_manager

def main():
    logger.info("Starting Perplex-lite application")
    app = build_app()
    thread_id = "cli-user-1"
    
    # Create a new conversation for this session
    conversation_id = conversation_manager.create_conversation("cli-user")
    logger.info(f"Created conversation: {conversation_id}")
    
    print("Perplex-lite (Lambda-backed) with Conversation Logging")
    print("Type 'exit' to quit, 'list' to see past conversations, 'continue <id>' to continue a conversation")
    print(f"Current conversation ID: {conversation_id}")

    while True:
        user_input = input("\nYou: ").strip()
        
        if not user_input:
            continue
            
        if user_input.lower() == "exit":
            logger.info("User requested exit")
            break
        
        if user_input.lower() == "list":
            # List past conversations
            conversations = conversation_manager.list_user_conversations("cli-user", limit=10)
            if conversations:
                print("\nPast Conversations:")
                for conv in conversations:
                    print(f"  {conv['conversation_id']} - {conv['updated_at'][:19]} - {conv['message_count']} messages")
                    print(f"    Last: {conv['last_message_preview']}")
            else:
                print("No past conversations found.")
            continue
        
        if user_input.lower().startswith("continue "):
            # Continue an existing conversation
            target_conversation_id = user_input[9:].strip()
            conversation_state = conversation_manager.continue_conversation(target_conversation_id)
            
            if conversation_state:
                conversation_id = target_conversation_id
                print(f"Continuing conversation: {conversation_id}")
                print(f"Previous messages: {len(conversation_state['messages'])}")
            else:
                print(f"Conversation {target_conversation_id} not found.")
            continue

        # Process the query
        q = user_input
        logger.info(f"Processing query: {q}")
        
        try:
            # Get current conversation state
            current_state = app.get_state({"configurable": {"thread_id": thread_id}})
            current_messages = current_state.values.get("messages", []) if current_state.values else []
            
            # Add new user message
            current_messages.append({"role": "user", "content": q})
            
            # Prepare processing metadata
            processing_metadata = {
                "start_time": datetime.now().isoformat(),
                "conversation_id": conversation_id
            }
            
            out = app.invoke(
                {
                    "messages": current_messages,
                    "user_query": q,
                    "iteration_count": 0,
                    "conversation_id": conversation_id,
                    "processing_metadata": processing_metadata
                },
                config={"configurable": {"thread_id": thread_id}}
            )
            
            # Add assistant response to conversation
            if "answer" in out:
                current_messages.append({"role": "assistant", "content": out["answer"]})

            # Log distiller results if available
            if "distiller_result" in out:
                distiller_result = out["distiller_result"]
                logger.info(f"Distiller processed {distiller_result.get('total_original_docs', 0)} docs, "
                          f"filtered out {distiller_result.get('filtered_out_count', 0)}, "
                          f"kept {len(distiller_result.get('distilled_docs', []))}")
            
            # Log QA results if available
            if "qa_result" in out:
                qa_result = out["qa_result"]
                logger.info(f"QA evaluation: quality_score={qa_result.get('quality_score', 0):.2f}, "
                          f"needs_more_data={qa_result.get('needs_more_data', False)}, "
                          f"iterations={out.get('iteration_count', 0)}")
            
            # Prepare comprehensive processing metadata for logging
            full_processing_metadata = conversation_manager.prepare_processing_metadata(out)
            
            # Log the complete conversation turn
            conversation_manager.log_conversation_turn(
                conversation_id=conversation_id,
                user_query=q,
                assistant_response=out["answer"],
                citations=out.get("citations", []),
                processing_metadata=full_processing_metadata
            )
            
            logger.info(f"Generated answer with {len(out.get('citations', []))} citations")
            print("\nAssistant:\n" + out["answer"])
            
            if out.get("citations"):
                print("\nSources:")
                for i, u in enumerate(out.get("citations",[]), 1):
                    print(f"[{i}] {u}")
            else:
                print("\n(Answer based on conversation context)")

        except Exception as e:
            logger.error(f"Error processing query '{q}': {str(e)}")
            print(f"\nError: {str(e)}")
            print("Please try again or check the logs for more details.")

if __name__ == "__main__":
    main()
