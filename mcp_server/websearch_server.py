"""
MCP tool server exposing a single tool: websearch(query, max_urls)
It calls your AWS Lambda and returns decoded markdown per URL.
Run: python -m mcp_server.websearch_server
"""

import os
import asyncio
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from aws.lambda_client import invoke_websearch_lambda

# Minimal MCP app using the 'mcp' Python package.
# Docs: https://github.com/modelcontextprotocol/python-sdk (API may evolve)

from mcp.server.fastmcp import FastMCP, Tool

class WebSearchArgs(BaseModel):
    query: str = Field(..., description="User query")
    max_urls: Optional[int] = Field(8, description="Max URLs to fetch")

app = FastMCP("websearch-tool")

@app.tool("websearch", args_schema=WebSearchArgs)
def websearch(query: str, max_urls: int = 8) -> List[Dict]:
    """
    Calls the Lambda and returns list of {url, markdown}.
    """
    results = invoke_websearch_lambda(query, max_urls=max_urls)
    # Keep payload small; no scoring here
    return [{"url": r["url"], "markdown": r["markdown"]} for r in results]

if __name__ == "__main__":
    # FastMCP runs a stdio server by default
    app.run()
