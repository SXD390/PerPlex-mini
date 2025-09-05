import os
import logging
import json
from typing import Dict
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

# Thinking agent LLM
llm = None

def get_llm():
    global llm
    if llm is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash", 
            temperature=0.2,  # Slightly higher for more creative and diverse query generation
            google_api_key=api_key
        )
    return llm

THINKING_PROMPT = """You are a thinking agent that analyzes user queries and conversation context to determine what information is needed.

Your job is to:
1. Analyze the user's query in the context of the conversation history
2. Elaborately rephrase the user's intent to better understand what they're looking for
3. Determine if web search is needed to answer the query comprehensively
4. If web search is needed, formulate diverse and comprehensive search queries that capture different angles
5. Provide reasoning for your decisions

Conversation History:
{messages}

Current User Query: {user_query}

Respond with a JSON object containing:
{{
  "needs_web_search": true/false,
  "search_queries": ["query1", "query2", ...],
  "reasoning": "Why you made these decisions",
  "context_analysis": "What you understand about the conversation context",
  "elaborated_intent": "A detailed rephrasing of what the user is actually looking for, including implicit needs and comprehensive scope"
}}

Rules:
- ALWAYS provide an elaborated_intent that expands on what the user is really asking for
- For early queries (1st or 2nd), be especially comprehensive in understanding the user's broader intent
- Only suggest web search if the query requires current/recent information not in the conversation
- If the query is a follow-up to previous questions, consider the context

Search Query Diversity Strategy:
- Create {min_q}-{max_q} diverse search queries that cover different aspects and angles
- Use varied terminology, synonyms, and alternative phrasings
- Include different perspectives: technical, practical, historical, current trends, controversies
- Mix broad and specific queries to capture both overview and detailed information
- Consider different timeframes: recent developments, historical context, future implications
- Include related concepts and adjacent topics that might provide valuable context
- Use different search intents: "what is", "how does", "why", "when", "where", "who", "latest", "trends", "impact", "benefits", "challenges"

Examples of diverse query patterns:
- Main topic + "overview" or "introduction"
- Main topic + "latest developments" or "recent news"
- Main topic + "how it works" or "process"
- Main topic + "benefits and challenges" or "pros and cons"
- Main topic + "examples" or "case studies"
- Main topic + "future" or "trends"
- Related concept + "impact on" + main topic

- If no web search is needed, set search_queries to an empty array
- Think about what additional information would make the response more valuable and comprehensive
"""

def thinking_node(state: Dict) -> Dict:
    user_query = state["user_query"]
    messages = state.get("messages", [])
    
    logger.info(f"Thinking agent analyzing query: {user_query}")
    logger.info(f"Conversation history length: {len(messages)}")
    
    # Format conversation history for the prompt
    formatted_messages = []
    for msg in messages[-6:]:  # Last 6 messages for context
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        formatted_messages.append(f"{role}: {content}")
    
    conversation_text = "\n".join(formatted_messages) if formatted_messages else "No previous conversation"
    
    try:
        mode = state.get("mode", "fast").lower()
        # Mode-aware query targets
        if mode == "thorough":
            min_q, max_q = 7, 10
        else:
            min_q, max_q = 3, 5

        prompt = THINKING_PROMPT.format(
            messages=conversation_text,
            user_query=user_query,
            min_q=min_q,
            max_q=max_q
        )
        
        resp = get_llm().invoke([{"role": "user", "content": prompt}])
        logger.debug(f"Thinking agent response: {resp.content}")
        
        # Extract JSON from response
        content = resp.content.strip()
        if content.startswith('```json') and content.endswith('```'):
            content = content[7:-3].strip()
        elif content.startswith('```') and content.endswith('```'):
            content = content[3:-3].strip()
        
        thinking_result = json.loads(content)
        
        # Validate the response structure
        required_fields = ["needs_web_search", "search_queries", "reasoning", "context_analysis", "elaborated_intent"]
        for field in required_fields:
            if field not in thinking_result:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate query count (mode-aware)
        query_count = len(thinking_result['search_queries'])
        max_allowed = 10 if mode == "thorough" else 5
        min_required = 7 if mode == "thorough" else 1
        if query_count > max_allowed:
            logger.warning(f"Too many queries ({query_count}), limiting to {max_allowed}")
            thinking_result['search_queries'] = thinking_result['search_queries'][:max_allowed]
        elif query_count == 0 and thinking_result['needs_web_search']:
            logger.warning("Web search needed but no queries provided, adding fallback query")
            thinking_result['search_queries'] = [user_query]
        elif query_count < min_required and thinking_result['needs_web_search']:
            logger.info(f"Fewer than desired queries generated for mode {mode} ({query_count} < {min_required})")
        
        logger.info(f"Thinking result: needs_search={thinking_result['needs_web_search']}, queries={len(thinking_result['search_queries'])}")
        logger.info(f"Elaborated intent: {thinking_result['elaborated_intent']}")
        logger.info(f"Reasoning: {thinking_result['reasoning']}")
        logger.info(f"Search queries: {thinking_result['search_queries']}")
        
        return {"thinking_result": thinking_result}
        
    except Exception as e:
        logger.error(f"Thinking agent failed: {e}")
        # Fallback: assume web search is needed
        fallback_result = {
            "needs_web_search": True,
            "search_queries": [user_query],
            "reasoning": f"Thinking agent failed ({str(e)}), falling back to direct search",
            "context_analysis": "Unable to analyze context due to error",
            "elaborated_intent": f"User is asking: {user_query} (intent analysis failed due to error)"
        }
        return {"thinking_result": fallback_result}
