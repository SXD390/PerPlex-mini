from typing import TypedDict, List, Dict, Any, Optional

class Doc(TypedDict):
    url: str
    markdown: str
    score: float

class ThinkingResult(TypedDict):
    needs_web_search: bool
    search_queries: List[str]
    reasoning: str
    context_analysis: str

class DistilledDoc(TypedDict):
    url: str
    title: str
    relevant_content: str
    relevance_score: float
    source_quality: str  # "high", "medium", "low"

class DistillerResult(TypedDict):
    distilled_docs: List[DistilledDoc]
    total_original_docs: int
    filtered_out_count: int
    quality_summary: str

class QAResult(TypedDict):
    needs_more_data: bool
    missing_aspects: List[str]
    quality_score: float
    improvement_suggestions: List[str]
    refined_query: Optional[str]
    should_reformat: bool

class GraphState(TypedDict):
    messages: List[Dict[str, str]]   # chat history
    user_query: str                  # latest user query
    thinking_result: Optional[ThinkingResult]  # thinking agent output
    raw_docs: List[Doc]              # raw docs from Lambda
    distiller_result: Optional[DistillerResult]  # distiller agent output
    answer: str                      # synthesized answer (with cites)
    citations: List[str]             # urls used
    qa_result: Optional[QAResult]    # QA agent output
    iteration_count: int             # number of QA iterations
    conversation_id: str             # unique conversation identifier
    conversation_title: Optional[str]  # generated conversation title
    processing_metadata: Dict[str, Any]  # metadata for logging
    diagnostics: Dict[str, Any]
