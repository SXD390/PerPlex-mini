import os
import logging
import json
from typing import Dict
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

llm = None

def get_llm():
    global llm
    if llm is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            temperature=0.3,  # Lower temperature for more consistent titles
            google_api_key=api_key
        )
    return llm

TITLE_PROMPT = """You are a title generation agent. Your task is to create a concise, descriptive title for a conversation based on the user's first query and the assistant's response.

The title should be:
- 3-8 words long
- Descriptive and specific to the topic
- Professional and clear
- Avoid generic terms like "Question" or "Query"
- Capture the main subject matter

User's Query: {user_query}

Assistant's Response: {assistant_response}

Generate a concise title for this conversation. Respond with just the title, no quotes or additional text.

Examples:
- "MacBook vs Dell Laptop Comparison"
- "Neodymium vs Ferrite Magnets"
- "Skoda Slavia vs Hyundai Verna 2025"
- "Python Flask Web Development"
- "AWS Lambda Function Setup"
"""

def title_agent_node(state: Dict) -> Dict:
    """Generate a title for the conversation based on the first exchange"""
    user_query = state.get("user_query", "")
    assistant_response = state.get("answer", "")
    conversation_id = state.get("conversation_id", "")
    
    # Only generate title if we don't already have one
    if state.get("conversation_title"):
        logger.info(f"Conversation {conversation_id} already has a title, skipping title generation")
        return {"title_generated": False}
    
    logger.info(f"Generating title for conversation {conversation_id}")
    logger.info(f"User query: {user_query[:100]}...")
    logger.info(f"Response length: {len(assistant_response)} characters")
    
    content = TITLE_PROMPT.format(
        user_query=user_query,
        assistant_response=assistant_response[:2000]  # Limit response length for title generation
    )
    
    try:
        resp = get_llm().invoke([{"role": "user", "content": content}])
        title = resp.content.strip()
        
        # Clean up the title (remove quotes, extra whitespace)
        title = title.strip('"\'')
        title = ' '.join(title.split())  # Remove extra whitespace
        
        # Ensure title is not too long
        if len(title) > 60:
            title = title[:57] + "..."
        
        logger.info(f"Generated title: '{title}'")
        
        return {"conversation_title": title, "title_generated": True}
        
    except Exception as e:
        logger.error(f"Title agent failed: {e}")
        # Fallback to a generic title based on user query
        fallback_title = user_query[:50] + "..." if len(user_query) > 50 else user_query
        logger.info(f"Using fallback title: '{fallback_title}'")
        return {"conversation_title": fallback_title, "title_generated": True}
