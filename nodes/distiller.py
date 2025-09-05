import os
import logging
import json
import re
from typing import Dict, List
from langchain_google_genai import ChatGoogleGenerativeAI
from utils.text import keyword_score

logger = logging.getLogger(__name__)

# Source quality domains
OFFICIAL = ("docs.", "developer.", "learn.", "support.", "help.", "wikipedia.org", "arxiv.org", "who.int", "nih.gov")
COMMUNITY = ("reddit.com", "quora.com", "stackoverflow.com", "medium.com")

def source_quality(url: str) -> float:
    """Rate source quality from 0.0 to 1.0 based on domain"""
    u = url.lower()
    if any(k in u for k in OFFICIAL): 
        return 1.0
    if any(k in u for k in COMMUNITY): 
        return 0.6
    return 0.8

# Distiller agent LLM
llm = None

def get_llm():
    global llm
    if llm is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash", 
            temperature=0.1,  # Low temperature for consistent filtering
            google_api_key=api_key
        )
    return llm

DISTILLER_PROMPT = """You are a distiller agent responsible for filtering and formatting web search results.

Your job is to:
1. Filter out irrelevant URLs and content
2. Extract only content relevant to the search query
3. Assess source quality and relevance
4. Format the information cleanly for the thinking agent

Search Query: {search_query}
Original Results Count: {doc_count}

Web Search Results:
{raw_results}

Instructions:
- Remove URLs that are completely irrelevant to the query (e.g., government forms, unrelated services)
- Extract comprehensive and detailed content snippets from each document (up to 2000 chars)
- Include as much relevant information as possible from each source
- Assess source quality: "high" (reputable sources like Wikipedia, official sites), "medium" (news sites, blogs), "low" (user-generated content, forums)
- Rate relevance from 0.0 to 1.0 based on how well the content answers the search query
- Keep only the top 5-8 most relevant and high-quality results
- Prioritize sources with substantial, detailed content that can contribute to a comprehensive answer

Respond with a JSON object:
{{
  "distilled_docs": [
    {{
      "url": "https://example.com",
      "title": "Extracted title",
      "relevant_content": "Only the most relevant content snippet (max 2000 chars)",
      "relevance_score": 0.85,
      "source_quality": "high"
    }}
  ],
  "total_original_docs": 10,
  "filtered_out_count": 5,
  "quality_summary": "Brief summary of filtering decisions"
}}

Filter out URLs containing:
- Government forms (.gov forms, applications)
- Unrelated services (SSA, IRS, etc. unless directly relevant)
- Login pages, account management
- Generic directory listings
- Spam or low-quality content
"""

def distiller_node(state: Dict) -> Dict:
    raw_docs = state.get("raw_docs", [])
    thinking_result = state.get("thinking_result", {})
    search_queries = thinking_result.get("search_queries", [])
    
    if not raw_docs:
        logger.info("No raw documents to distill")
        return {"distiller_result": {
            "distilled_docs": [],
            "total_original_docs": 0,
            "filtered_out_count": 0,
            "quality_summary": "No documents to process"
        }}
    
    # Use the first search query as context for distillation
    search_query = search_queries[0] if search_queries else "general search"
    
    logger.info(f"Distilling {len(raw_docs)} raw documents for query: {search_query}")
    
    # Format raw results for the LLM
    formatted_results = []
    for i, doc in enumerate(raw_docs):
        url = doc.get("url", "")
        markdown = doc.get("markdown", "")
        formatted_results.append(f"Document {i+1}:\nURL: {url}\nContent: {markdown[:1000]}...")
    
    raw_results_text = "\n\n".join(formatted_results)
    
    try:
        prompt = DISTILLER_PROMPT.format(
            search_query=search_query,
            doc_count=len(raw_docs),
            raw_results=raw_results_text
        )
        
        resp = get_llm().invoke([{"role": "user", "content": prompt}])
        logger.debug(f"Distiller response: {resp.content}")
        
        # Extract JSON from response
        content = resp.content.strip()
        if content.startswith('```json') and content.endswith('```'):
            content = content[7:-3].strip()
        elif content.startswith('```') and content.endswith('```'):
            content = content[3:-3].strip()
        
        distiller_result = json.loads(content)
        
        # Validate the response structure
        if "distilled_docs" not in distiller_result:
            raise ValueError("Missing distilled_docs in response")
        
        # Additional filtering for obviously irrelevant URLs
        filtered_docs = []
        for doc in distiller_result["distilled_docs"]:
            url = doc.get("url", "")
            if is_relevant_url(url, search_query):
                filtered_docs.append(doc)
            else:
                logger.debug(f"Filtered out irrelevant URL: {url}")
        
        distiller_result["distilled_docs"] = filtered_docs
        distiller_result["filtered_out_count"] = len(raw_docs) - len(filtered_docs)
        
        logger.info(f"Distilled {len(filtered_docs)} relevant documents from {len(raw_docs)} raw documents")
        logger.info(f"Quality summary: {distiller_result.get('quality_summary', 'No summary')}")
        
        return {"distiller_result": distiller_result}
        
    except Exception as e:
        logger.error(f"Distiller agent failed: {e}")
        # Fallback: basic filtering
        return fallback_distillation(raw_docs, search_query)

def is_relevant_url(url: str, query: str) -> bool:
    """Additional URL filtering based on patterns"""
    irrelevant_patterns = [
        r'\.gov/.*form',
        r'\.gov/.*application',
        r'\.gov/.*login',
        r'\.gov/.*account',
        r'ssa\.gov',
        r'irs\.gov',
        r'uscis\.gov',
        r'login\.',
        r'signin\.',
        r'register\.',
        r'account\.',
        r'profile\.',
        r'dashboard\.',
        r'admin\.',
        r'manage\.',
    ]
    
    query_lower = query.lower()
    url_lower = url.lower()
    
    # Check for irrelevant patterns
    for pattern in irrelevant_patterns:
        if re.search(pattern, url_lower):
            return False
    
    # Check if URL contains query-related terms
    query_terms = set(re.findall(r'\w+', query_lower))
    url_terms = set(re.findall(r'\w+', url_lower))
    
    # If URL has some overlap with query terms, it's more likely relevant
    overlap = len(query_terms.intersection(url_terms))
    # More lenient: allow URLs even with minimal overlap or if query is short
    return overlap > 0 or len(query_terms) < 5  # Allow if query is short or has any overlap

def fallback_distillation(raw_docs: List[Dict], search_query: str) -> Dict:
    """Fallback distillation when LLM fails"""
    logger.warning("Using fallback distillation due to LLM failure")
    
    distilled_docs = []
    for doc in raw_docs:
        url = doc.get("url", "")
        markdown = doc.get("markdown", "")
        
        if not is_relevant_url(url, search_query):
            continue
            
        # Basic relevance scoring (more lenient)
        relevance_score = keyword_score(search_query, markdown)
        
        # Extract title (first line or heading)
        lines = markdown.split('\n')
        title = lines[0][:100] if lines else url
        
        # Truncate content (increased length for more context)
        relevant_content = markdown[:2000] + "..." if len(markdown) > 2000 else markdown
        
        # Improved source quality assessment
        source_quality_score = source_quality(url)
        
        # More lenient scoring: 50% relevance + 50% source quality (less strict on relevance)
        combined_score = 0.5 * relevance_score + 0.5 * source_quality_score
        
        distilled_docs.append({
            "url": url,
            "title": title,
            "relevant_content": relevant_content,
            "relevance_score": relevance_score,
            "source_quality": "high" if source_quality_score >= 0.8 else "medium" if source_quality_score >= 0.6 else "low",
            "combined_score": combined_score
        })
    
    # Sort by combined score and take top 8 (more lenient)
    distilled_docs.sort(key=lambda x: x["combined_score"], reverse=True)
    distilled_docs = distilled_docs[:8]
    
    return {"distiller_result": {
        "distilled_docs": distilled_docs,
        "total_original_docs": len(raw_docs),
        "filtered_out_count": len(raw_docs) - len(distilled_docs),
        "quality_summary": "Fallback distillation applied due to LLM failure"
    }}
