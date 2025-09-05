import os
import logging
import json
from typing import Dict, List
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

# QA agent LLM
llm = None

def get_llm():
    global llm
    if llm is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash", 
            temperature=0.1,  # Low temperature for consistent evaluation
            google_api_key=api_key
        )
    return llm

QA_PROMPT = """You are a Quality Assurance agent that evaluates the completeness and quality of responses.

Your job is to:
1. Evaluate if the response adequately addresses the user's question
2. Identify missing aspects or information gaps
3. Determine if additional data is needed
4. Suggest improvements for better formatting or structure
5. Decide if the response needs more comprehensive information

User Query: {user_query}
User's Elaborated Intent: {elaborated_intent}
Current Response: {current_response}
Available Sources: {source_count} sources with {citation_count} citations
Mode: {mode}

Evaluate the response and respond with a JSON object:
{{
  "needs_more_data": true/false,
  "missing_aspects": ["aspect1", "aspect2", ...],
  "quality_score": 0.0-1.0,
  "improvement_suggestions": ["suggestion1", "suggestion2", ...],
  "refined_query": "specific query for additional data if needed",
  "should_reformat": true/false
}}

Evaluation Criteria:
- COMPLETENESS: Does the response fully address the user's question?
- DEPTH: Is the information detailed and comprehensive enough?
- STRUCTURE: Is the response well-organized and easy to follow?
- ACCURACY: Are the facts presented correctly based on sources?
- RELEVANCE: Does the response stay focused on the user's intent?
 - CITATIONS: Are citations present and correctly referenced?
 - LENGTH: If mode is "thorough", the response MUST be at least 4000 words.

Rules:
- Fast mode: prefer reformatting; do not request additional data unless the response is critically insufficient.
- Thorough mode: require >=4000 words, comprehensive coverage across all relevant aspects; allow requesting more data up to two times.
- Set needs_more_data=true ONLY if the response is incomplete or missing critical information that cannot be fixed by reformatting
- Set should_reformat=true if the response needs better organization, structure, or expansion from existing sources
- Provide specific missing_aspects that should be addressed
- Give a quality_score from 0.0 (poor) to 1.0 (excellent)
- If needs_more_data=true, provide a refined_query for additional search
- Maximum 2 QA iterations in thorough mode to avoid loops; 0 in fast mode
- Be conservative in fast mode: prefer reformatting over additional searches
"""

def qa_agent_node(state: Dict) -> Dict:
    user_query = state["user_query"]
    current_response = state.get("answer", "")
    thinking_result = state.get("thinking_result", {})
    distiller_result = state.get("distiller_result", {})
    iteration_count = state.get("iteration_count", 0)
    mode = state.get("mode", "fast").lower()
    
    # Skip QA if we've already done too many iterations (max 2 QA iterations)
    if iteration_count >= 2:
        logger.info(f"QA agent skipping evaluation - maximum iterations reached ({iteration_count})")
        return {"qa_result": {
            "needs_more_data": False,
            "missing_aspects": [],
            "quality_score": 0.7,
            "improvement_suggestions": ["Maximum QA iterations reached (2)"],
            "refined_query": None,
            "should_reformat": False
        }}
    
    elaborated_intent = thinking_result.get("elaborated_intent", user_query)
    source_count = len(distiller_result.get("distilled_docs", []))
    citation_count = len(state.get("citations", []))
    
    logger.info(f"QA agent evaluating response (iteration {iteration_count + 1}, mode={mode})")
    logger.info(f"Response length: {len(current_response)} characters")
    logger.info(f"Sources: {source_count}, Citations: {citation_count}")
    
    try:
        prompt = QA_PROMPT.format(
            user_query=user_query,
            elaborated_intent=elaborated_intent,
            current_response=current_response,
            source_count=source_count,
            citation_count=citation_count,
            mode=mode
        )
        
        resp = get_llm().invoke([{"role": "user", "content": prompt}])
        logger.debug(f"QA agent response: {resp.content}")
        
        # Extract JSON from response
        content = resp.content.strip()
        if content.startswith('```json') and content.endswith('```'):
            content = content[7:-3].strip()
        elif content.startswith('```') and content.endswith('```'):
            content = content[3:-3].strip()
        
        qa_result = json.loads(content)
        
        # Validate the response structure
        required_fields = ["needs_more_data", "missing_aspects", "quality_score", "improvement_suggestions", "refined_query", "should_reformat"]
        for field in required_fields:
            if field not in qa_result:
                raise ValueError(f"Missing required field: {field}")
        
        # Enforce mode-specific policies
        # Length check for thorough mode (words)
        if mode == "thorough":
            word_count = len(current_response.split())
            if word_count < 4000:
                logger.info(f"QA: Response below length requirement for thorough mode ({word_count} < 4000 words)")
                # Prefer additional data if sources seem thin; otherwise reformat/expand
                if source_count < 4:
                    qa_result["needs_more_data"] = True
                else:
                    qa_result["should_reformat"] = True

        if mode == "fast":
            # In fast mode, do not request more data; prefer reformat only
            qa_result["needs_more_data"] = False
            # Ensure we at least consider reformatting
            if not qa_result.get("should_reformat", False):
                qa_result["should_reformat"] = True

        logger.info(f"QA evaluation: needs_more_data={qa_result['needs_more_data']}, quality_score={qa_result['quality_score']:.2f}")
        logger.info(f"Missing aspects: {qa_result['missing_aspects']}")
        logger.info(f"Improvement suggestions: {qa_result['improvement_suggestions']}")
        
        return {"qa_result": qa_result}
        
    except Exception as e:
        logger.error(f"QA agent failed: {e}")
        # Fallback: assume response is adequate
        fallback_result = {
            "needs_more_data": False,
            "missing_aspects": [],
            "quality_score": 0.6,
            "improvement_suggestions": [f"QA evaluation failed: {str(e)}"],
            "refined_query": None,
            "should_reformat": False
        }
        return {"qa_result": fallback_result}

def should_continue_qa(state: Dict) -> str:
    """Determine if we should continue with QA or finish"""
    qa_result = state.get("qa_result", {})
    iteration_count = state.get("iteration_count", 0)
    mode = state.get("mode", "fast")
    
    # Fast mode: always proceed to formatter once
    if mode == "fast":
        logger.info("Fast mode: routing to formatter")
        return "reformat"

    # Thorough mode with up to 2 iterations
    max_iter = 2
    if iteration_count >= max_iter:
        logger.info(f"Maximum QA iterations reached ({iteration_count}) for mode {mode}, finishing")
        return "end"
    
    if qa_result.get("needs_more_data", False):
        logger.info(f"QA iteration {iteration_count + 1}: needs more data, triggering search")
        return "search"
    elif qa_result.get("should_reformat", False):
        logger.info(f"QA iteration {iteration_count + 1}: needs reformatting")
        return "reformat"
    else:
        logger.info(f"QA iteration {iteration_count + 1}: response is adequate, ending")
        return "end"
