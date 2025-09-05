import os
import logging
from typing import Dict, List
from langchain_google_genai import ChatGoogleGenerativeAI
from utils.text import keyword_score

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
            temperature=0.3,  # Slightly higher for more creative/detailed responses
            google_api_key=api_key,
            max_output_tokens=8192  # Explicitly set higher token limit
        )
    return llm

PROMPT = """Answer the user's question comprehensively and elaborately using ONLY the provided sources, which are markdown excerpts.

Your response should be:
- DETAILED and COMPREHENSIVE - provide rich, thorough information (aim for 2000+ characters)
- WELL-STRUCTURED with clear sections and subsections
- INFORMATIVE - include specific details, examples, and context
- PROFESSIONAL - use proper formatting and clear explanations
- COMPLETE - cover all relevant aspects of the question
- DIRECT - provide the full answer immediately, do NOT ask what the user wants to know next
- SELF-CONTAINED - include all necessary information in your response
- EXTENSIVE - provide as much relevant detail as possible from the sources

IMPORTANT: Do NOT ask questions like "What would you like to know about next?" or "Should we start with X?" 
Instead, provide a complete, comprehensive answer that covers all aspects of the question.

Cite with [^n] markers and list sources at the end as numbered URLs.
If something is uncertain, say so clearly.

Question: {q}

Sources (use what's relevant; each starts with [^n] URL):
{ctx}

Provide a comprehensive, detailed answer that thoroughly addresses the user's question. Be extensive and detailed - aim for a substantial response that covers all aspects comprehensively.
"""

def synthesize_node(state: Dict) -> Dict:
    user_query = state["user_query"]
    distiller_result = state.get("distiller_result", {})
    thinking_result = state.get("thinking_result", {})
    messages = state.get("messages", [])
    
    logger.info(f"Synthesizing answer for query: {user_query}")
    logger.info(f"Web search needed: {thinking_result.get('needs_web_search', False)}")

    # If no web search was needed, use conversation context instead
    if not thinking_result.get("needs_web_search", False):
        logger.info("No web search needed, using conversation context")
        return synthesize_from_context(user_query, messages, thinking_result)
    
    distilled_docs = distiller_result.get("distilled_docs", [])
    logger.info(f"Processing {len(distilled_docs)} distilled documents")
    
    # Fail-soft synthesis: check for minimum evidence
    total_content_length = sum(len(d.get("relevant_content", "")) for d in distilled_docs)
    if not distilled_docs or total_content_length < 400:
        logger.info(f"Insufficient evidence (docs: {len(distilled_docs)}, content: {total_content_length} chars), using conversation context")
        return synthesize_from_context(user_query, messages, thinking_result)
    
    # Use distilled documents for synthesis
    ctx_lines, citations = [], []
    for i, doc in enumerate(distilled_docs, start=1):
        url = doc.get("url", "")
        title = doc.get("title", "")
        content = doc.get("relevant_content", "")
        relevance_score = doc.get("relevance_score", 0.0)
        source_quality = doc.get("source_quality", "medium")
        
        ctx_lines.append(f"[^{i}] {title} ({source_quality} quality, relevance: {relevance_score:.2f})\n{url}\n{content}")
        citations.append(url)
        
        logger.debug(f"Doc {i}: {title} - {source_quality} quality, {relevance_score:.2f} relevance")

    content = PROMPT.format(q=user_query, ctx="\n\n".join(ctx_lines))
    logger.debug(f"Prompt length: {len(content)} characters")
    
    try:
        resp = get_llm().invoke([{"role":"user","content":content}])
        logger.info(f"Generated answer with {len(citations)} citations")
        logger.debug(f"Answer length: {len(resp.content)} characters")
    except Exception as e:
        logger.error(f"Failed to generate answer: {e}")
        resp = type('obj', (object,), {'content': f"Error generating answer: {str(e)}"})
    
    # Filter citations to only show those actually used in the answer
    answer = resp.content
    import re
    # Support both [n] and [^n] formats
    used = sorted({int(m) for m in re.findall(r"\[(\d+)\]", answer) if m.isdigit()})
    used_hat = sorted({int(m) for m in re.findall(r"\[\^(\d+)\]", answer) if m.isdigit()})
    used = used + used_hat
    final_citations = []
    for i in used:
        idx = i - 1
        if 0 <= idx < len(distilled_docs):
            final_citations.append(distilled_docs[idx]["url"])
    
    logger.info(f"Filtered citations: {len(final_citations)} used out of {len(citations)} total")
    return {"answer": answer, "citations": final_citations}

def synthesize_from_context(user_query: str, messages: List[Dict], thinking_result: Dict) -> Dict:
    """Generate answer using conversation context when no web search is needed"""
    logger.info("Generating answer from conversation context")
    
    # Format conversation context
    context_lines = []
    for msg in messages[-10:]:  # Last 10 messages
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "assistant":
            context_lines.append(f"Previous answer: {content}")
        elif role == "user":
            context_lines.append(f"Previous question: {content}")
    
    context_text = "\n".join(context_lines) if context_lines else "No previous conversation"
    
    CONTEXT_PROMPT = """Answer the user's question using the conversation context provided. 
If the question is asking for clarification or follow-up on previous topics, use the context to provide a helpful response.
If you cannot answer based on the context alone, say so clearly.

IMPORTANT: Provide a complete, comprehensive answer. Do NOT ask questions like "What would you like to know about next?" or "Should we start with X?" 
Instead, provide the full answer that covers all aspects of the question.

Current question: {q}

Conversation context:
{ctx}

Provide a comprehensive, helpful response based on the available context."""

    try:
        content = CONTEXT_PROMPT.format(q=user_query, ctx=context_text)
        resp = get_llm().invoke([{"role":"user","content":content}])
        logger.info("Generated answer from conversation context")
        return {"docs": [], "answer": resp.content, "citations": []}
    except Exception as e:
        logger.error(f"Failed to generate context-based answer: {e}")
        return {"docs": [], "answer": f"I apologize, but I'm having trouble processing your request. {str(e)}", "citations": []}
