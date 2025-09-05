import os
import logging
from typing import Dict
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

# Reformat LLM
llm = None

def get_llm():
    global llm
    if llm is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash", 
            temperature=0.1,
            google_api_key=api_key
        )
    return llm

REFORMAT_PROMPT = """You are a response formatter that improves the structure and presentation of information for the end user.

Your job is to take the existing response and reformat it to directly answer the user's query in a more comprehensive and well-structured way:
- Better organized with clear sections and subsections
- More readable with proper formatting
- Better structured with logical flow
- More professional in presentation
- Address the user directly, not any internal processes

User Query: {user_query}
Current Response: {current_response}
Improvement Suggestions: {suggestions}

Reformat the response to directly answer the user's query in a more comprehensive, well-structured, and professional manner while maintaining all the original information and citations. The response should be written as if speaking directly to the user who asked the question.

Provide the improved response with the same citation format.
"""

def reformat_node(state: Dict) -> Dict:
    user_query = state["user_query"]
    current_response = state.get("answer", "")
    qa_result = state.get("qa_result", {})
    suggestions = qa_result.get("improvement_suggestions", [])
    
    logger.info("Reformatting response based on QA suggestions")
    logger.info(f"Suggestions: {suggestions}")
    
    try:
        prompt = REFORMAT_PROMPT.format(
            user_query=user_query,
            current_response=current_response,
            suggestions="; ".join(suggestions)
        )
        
        resp = get_llm().invoke([{"role": "user", "content": prompt}])
        
        logger.info("Response reformatted successfully")
        return {"answer": resp.content}
        
    except Exception as e:
        logger.error(f"Reformat failed: {e}")
        # Return original response if reformat fails
        return {"answer": current_response}
