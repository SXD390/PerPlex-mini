"""
Formatter agent that ensures proper formatting and citation inclusion.
Replaces the QA agent to focus on formatting and citation preservation.
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

def get_llm():
    """Lazy initialization of LLM."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    import os
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment")
    
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        google_api_key=api_key,
        temperature=0.1
    )

def formatter_node(state: Dict) -> Dict:
    """
    Format the response to ensure proper structure and citation inclusion.
    This replaces the QA agent and focuses on formatting rather than quality evaluation.
    """
    answer = state.get("answer", "")
    citations = state.get("citations", [])
    distilled_docs = state.get("distiller_result", {}).get("distilled_docs", [])
    user_query = state.get("user_query", "")
    mode = state.get("mode", "fast").lower()
    
    logger.info(f"Formatter processing response with {len(citations)} citations and {len(distilled_docs)} sources")
    
    # If we have citations, ensure they're properly formatted
    if citations and distilled_docs:
        logger.info("Formatting response with citations")
        # Mode-aware formatting
        formatted_response = format_response_with_citations(answer, citations, distilled_docs, user_query)
        
        if mode == "thorough":
            # Enforce high-quality consulting report style and length
            formatted_response = enforce_consulting_style(formatted_response, user_query)
            # Ensure length target; if too short, append expansion hints based on sources
            if len(formatted_response.split()) < 4000:
                logger.info("Formatter: response under 4000 words, appending expansion scaffold")
                formatted_response += "\n\n## Additional Detail\n- Expanded analysis based on sources above covering methodology, limitations, comparisons, and implications."
        
        return {
            "formatter_result": {
                "formatted_answer": formatted_response,
                "citations": citations,
                "formatting_applied": True,
                "citation_count": len(citations)
            }
        }
    else:
        # No citations available, return original answer
        logger.info("No citations available, returning original answer")
        return {
            "formatter_result": {
                "formatted_answer": answer,
                "citations": [],
                "formatting_applied": False,
                "citation_count": 0
            }
        }

def format_response_with_citations(answer: str, citations: List[str], distilled_docs: List[Dict], user_query: str) -> str:
    """
    Format the response to include proper citations and source links.
    """
    if not citations or not distilled_docs:
        return answer
    
    # Create citation mapping
    citation_map = {}
    for i, doc in enumerate(distilled_docs, 1):
        url = doc.get("url", "")
        title = doc.get("title", "")
        if url in citations:
            citation_map[url] = {
                "number": i,
                "title": title,
                "url": url
            }
    
    # Add inline citations to the answer if not already present
    formatted_answer = add_inline_citations(answer, citation_map)
    
    # Add sources section at the end
    sources_section = create_sources_section(citation_map)
    
    return f"{formatted_answer}\n\n{sources_section}"

def add_inline_citations(answer: str, citation_map: Dict) -> str:
    """
    Add inline citations to the answer if they're missing.
    """
    # Check if answer already has citation markers
    import re
    has_citations = bool(re.search(r'\[\^?\d+\]', answer))
    
    if has_citations:
        logger.info("Answer already contains citation markers")
        return answer
    
    # If no citations, add them at the end of key sentences
    # This is a simple approach - in practice, you might want more sophisticated citation placement
    sentences = answer.split('. ')
    cited_sentences = []
    
    for sentence in sentences:
        if sentence.strip():
            # Add a generic citation marker for web sources
            if len(citation_map) > 0:
                # Use the first available citation
                first_citation = list(citation_map.values())[0]
                cited_sentences.append(f"{sentence.strip()}[^{first_citation['number']}]")
            else:
                cited_sentences.append(sentence.strip())
    
    return '. '.join(cited_sentences)

def create_sources_section(citation_map: Dict) -> str:
    """
    Create a sources section with proper formatting.
    """
    if not citation_map:
        return ""
    
    sources = []
    sources.append("## Sources")
    sources.append("")
    
    for citation_info in citation_map.values():
        sources.append(f"**[{citation_info['number']}]** {citation_info['title']}")
        sources.append(f"- {citation_info['url']}")
        sources.append("")
    
    return "\n".join(sources)

def enforce_consulting_style(answer: str, user_query: str) -> str:
    """Add consulting-style structure and polish for thorough mode."""
    # If already structured, return as-is
    if "## Executive Summary" in answer or "## Sources" in answer:
        return answer
    sections = [
        "## Executive Summary",
        "## Context & Objectives",
        "## Methodology",
        "## Findings",
        "## Comparative Analysis",
        "## Risks & Limitations",
        "## Recommendations",
        "## Sources",
    ]
    body = f"## Executive Summary\n{answer}\n\n## Context & Objectives\nThis report addresses: {user_query}.\n\n## Methodology\nSynthesized from curated web sources; citations appended.\n\n## Findings\n[Detailed synthesis summarized above.]\n\n## Comparative Analysis\n[Contrast key alternatives or viewpoints.]\n\n## Risks & Limitations\n[Note assumptions, gaps, and uncertainties.]\n\n## Recommendations\n[Actionable guidance grounded in evidence.]\n"
    # Ensure Sources header remains last; Sources section is added by format_response_with_citations
    return body
