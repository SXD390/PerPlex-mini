import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List
from aws.lambda_client import invoke_websearch_lambda

logger = logging.getLogger(__name__)

def search_node(state: Dict) -> Dict:
    thinking_result = state.get("thinking_result")
    user_query = state["user_query"]
    
    if not thinking_result:
        logger.error("No thinking result available, cannot proceed with search")
        return {"raw_docs": []}
    
    if not thinking_result.get("needs_web_search", False):
        logger.info("Thinking agent determined no web search is needed")
        return {"raw_docs": []}
    
    search_queries = thinking_result.get("search_queries", [])
    logger.info(f"Thinking agent determined web search is needed")
    logger.info(f"Search queries: {search_queries}")
    logger.info(f"Reasoning: {thinking_result.get('reasoning', 'No reasoning provided')}")
    
    if not search_queries:
        logger.warning("No search queries provided by thinking agent")
        return {"raw_docs": []}
    
    # Execute searches for all queries in parallel and merge results
    all_docs = []
    seen_urls = set()

    def search_single_query(query: str) -> List[Dict]:
        """Search a single query and return results"""
        logger.info(f"Starting parallel search for: {query}")
        try:
            query_docs = invoke_websearch_lambda(query, max_urls=5)  # Fewer per query since we have multiple
            logger.info(f"Query '{query}' returned {len(query_docs)} documents")
            return query_docs
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return []

    # Execute all queries in parallel using ThreadPoolExecutor
    logger.info(f"Starting parallel execution of {len(search_queries)} search queries")
    
    with ThreadPoolExecutor(max_workers=min(len(search_queries), 5)) as executor:
        # Submit all queries
        future_to_query = {
            executor.submit(search_single_query, query): query 
            for query in search_queries
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_query):
            query = future_to_query[future]
            try:
                query_docs = future.result()
                
                # Process results and deduplicate
                for doc in query_docs:
                    url = doc.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_docs.append(doc)
                        logger.debug(f"Added doc: {url} - {len(doc.get('markdown', ''))} chars")
                    else:
                        logger.debug(f"Skipped duplicate URL: {url}")
                        
            except Exception as e:
                logger.error(f"Error processing results for query '{query}': {e}")

    logger.info(f"Parallel search completed. Total unique documents collected: {len(all_docs)}")
    return {"raw_docs": all_docs}
