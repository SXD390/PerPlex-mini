from typing import Dict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from state import GraphState
from nodes.thinking import thinking_node
from nodes.search_lambda import search_node
from nodes.distiller import distiller_node
from nodes.synthesize import synthesize_node
from nodes.formatter import formatter_node
from nodes.qa_agent import qa_agent_node, should_continue_qa
from nodes.reformat import reformat_node
from nodes.title_agent import title_agent_node

def increment_iteration(state: Dict) -> Dict:
    """Increment the iteration count when going back to search"""
    current_count = state.get("iteration_count", 0)
    return {"iteration_count": current_count + 1}

def should_generate_title(state: Dict) -> str:
    """Determine if we should generate a title for the conversation"""
    # Only generate title if:
    # 1. We don't already have a title
    # 2. This is the first response (iteration_count == 0)
    # 3. We have a complete answer
    
    has_title = bool(state.get("conversation_title"))
    is_first_response = state.get("iteration_count", 0) == 0
    has_answer = bool(state.get("answer"))
    
    if not has_title and is_first_response and has_answer:
        return "generate_title"
    else:
        return "end"

def build_app():
    g = StateGraph(GraphState)
    g.add_node("thinking", thinking_node)
    g.add_node("search", search_node)
    g.add_node("distiller", distiller_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("formatter", formatter_node)
    g.add_node("qa_agent", qa_agent_node)
    g.add_node("reformat", reformat_node)
    g.add_node("title_agent", title_agent_node)
    g.add_node("increment_iteration", increment_iteration)

    # Main flow
    g.add_edge(START, "thinking")
    g.add_edge("thinking", "search")
    g.add_edge("search", "distiller")
    g.add_edge("distiller", "synthesize")
    g.add_edge("synthesize", "qa_agent")

    # Conditional routing based on QA results and mode
    g.add_conditional_edges(
        "qa_agent",
        should_continue_qa,
        {
            "search": "increment_iteration",
            "reformat": "formatter",
            "end": "title_agent",
        },
    )

    g.add_edge("formatter", "title_agent")

    # After incrementing, go to thinking for new search
    g.add_edge("increment_iteration", "thinking")
    g.add_edge("reformat", "title_agent")
    
    # Title generation conditional routing
    g.add_conditional_edges(
        "title_agent",
        should_generate_title,
        {
            "generate_title": "title_agent",  # This shouldn't happen, but just in case
            "end": END  # Finish
        }
    )

    memory = MemorySaver()
    return g.compile(checkpointer=memory)
