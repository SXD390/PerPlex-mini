#!/usr/bin/env python3
import os
import json
import time
import base64
import logging
import traceback
from urllib.parse import urlparse
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3

# ---- Logging setup ----
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("lambda-search")

# ---- DDG client selection ----
try:
    from ddgs import DDGS  # pip install ddgs
    def ddg_text(query: str, max_results: int):
        with DDGS() as ddg:
            return list(ddg.text(query, max_results=max_results))
    log.debug("ddg: using ddgs package")
except Exception as e:
    log.warning("ddg: ddgs import failed (%s); falling back to duckduckgo_search", e)
    from duckduckgo_search import DDGS  # legacy
    def ddg_text(query: str, max_results: int):
        with DDGS() as ddg:
            return list(ddg.text(query, max_results=max_results))

# ---- Configs ----
DEFAULT_RESULTS_LIMIT = int(os.getenv("DDG_MAX_RESULTS", "10"))
lambda_client = boto3.client("lambda")

def _normalize_results(raw: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for item in raw:
        title = (item.get("title") or "").strip()
        url = (item.get("href") or "").strip()
        if not title or not url or not url.startswith(("http://", "https://")):
            continue
        try:
            u = urlparse(url)
            key = (u.scheme, u.netloc.lower(), u.path)
        except Exception:
            key = url
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "url": url})
        if len(out) >= limit:
            break
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out

def call_lambda2(url: str, lambda2_arn: str) -> Dict[str, Any]:
    t0 = time.time()
    try:
        resp = lambda_client.invoke(
            FunctionName=lambda2_arn,
            InvocationType="RequestResponse",
            Payload=json.dumps({"url": url}).encode("utf-8"),
        )
        payload_text = resp.get("Payload").read() if resp.get("Payload") else b"{}"
        payload = json.loads(payload_text or "{}")
        if payload.get("statusCode") == 200:
            body = json.loads(payload.get("body", "{}"))
            elapsed = int((time.time()-t0)*1000)
            if body.get("success"):
                log.info("fetch:ok url=%s len=%s elapsed_ms=%d",
                         url, body.get("content_length"), elapsed)
            else:
                log.info("fetch:fail url=%s err=%s elapsed_ms=%d",
                         url, body.get("error"), elapsed)
            return body
        err = payload.get("body", "Unknown error")
        log.warning("fetch:http_non200 url=%s status=%s err=%s",
                    url, payload.get("statusCode"), err)
        return {"success": False, "error": err, "url": url}
    except Exception as e:
        log.error("fetch:invoke exception url=%s err=%s\n%s",
                  url, e, traceback.format_exc())
        return {"success": False, "error": str(e), "url": url}

def lambda_handler(event, context):
    req_id = getattr(context, "aws_request_id", "n/a")
    log.info("handler:start request_id=%s eventKeys=%s", req_id, list((event or {}).keys()))
    try:
        query = (event or {}).get("query", "").strip()
        if not query:
            log.warning("validation:query missing")
            return {
                "statusCode": 400,
                "body": json.dumps({"success": False, "error": "Query parameter is required", "results": []}),
            }

        lambda2_arn = os.environ.get("LAMBDA_LAYER2_ARN", "").strip()
        if not lambda2_arn:
            log.error("config:LAMBDA_LAYER2_ARN not set")
            return {
                "statusCode": 500,
                "body": json.dumps({"success": False, "error": "LAMBDA_LAYER2_ARN not set", "results": []}),
            }

        # 1) DDG search
        t_search0 = time.time()
        log.info("ddg:search query='%s' max=%d", query, DEFAULT_RESULTS_LIMIT)
        raw = ddg_text(query, max_results=DEFAULT_RESULTS_LIMIT)
        raw_count = len(raw) if isinstance(raw, list) else -1
        results = _normalize_results(raw, limit=DEFAULT_RESULTS_LIMIT)
        log.info("ddg:done raw_count=%d normalized=%d elapsed_ms=%d",
                 raw_count, len(results), int((time.time()-t_search0)*1000))

        for r in results:
            log.info("ddg:result rank=%d title='%s' url=%s", r["rank"], r["title"], r["url"])

        if not results:
            return {
                "statusCode": 200,
                "body": json.dumps({"success": False, "error": "No search results found", "query": query, "results": []}),
            }

        # 2) Fan-out to Lambda 2 (one worker per URL)
        max_workers = max(1, len(results))
        log.info("fanout:start urls=%d workers=%d", len(results), max_workers)

        def _invoke_one(r):
            data = call_lambda2(r["url"], lambda2_arn)
            if data.get("success"):
                md = data.get("markdown_content", "")
                return {
                    "rank": r["rank"],
                    "title": r["title"],
                    "url": r["url"],
                    "content_title": data.get("title", ""),
                    "markdown_content": base64.b64encode(md.encode("utf-8")).decode("utf-8"),
                    "content_length": len(md),
                    "success": True,
                }
            else:
                return {
                    "rank": r["rank"],
                    "title": r["title"],
                    "url": r["url"],
                    "error": data.get("error", "Unknown error"),
                    "success": False,
                }

        all_items = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_invoke_one, r) for r in results]
            for fut in as_completed(futs):
                try:
                    item = fut.result()
                    log.info("fanout:item rank=%s success=%s url=%s len=%s err=%s",
                             item.get("rank"), item.get("success"), item.get("url"),
                             item.get("content_length"), item.get("error"))
                    all_items.append(item)
                except Exception as e:
                    log.error("fanout:future exception err=%s\n%s", e, traceback.format_exc())

        # Keep order by original rank
        all_items.sort(key=lambda x: x["rank"])

        # Guardrail: only return items that actually have content
        successful_only = [x for x in all_items if x.get("success") and x.get("content_length", 0) > 0]
        ok = len(successful_only)
        filtered_out = len(all_items) - ok

        log.info("fanout:done total=%d returned_success=%d filtered_out=%d",
                 len(all_items), ok, filtered_out)

        resp = {
            "success": True,
            "query": query,
            "total_urls": len(results),         # how many we tried
            "successful_content": ok,           # how many with content we return
            "filtered_out": filtered_out,       # how many we dropped due to errors/empty content
            "results": successful_only,         # ONLY the items with content
        }
        log.info("handler:done request_id=%s tried=%d returned=%d",
                 req_id, len(results), ok)
        return {"statusCode": 200, "body": json.dumps(resp)}

    except Exception as e:
        log.error("handler:exception request_id=%s err=%s\n%s", req_id, e, traceback.format_exc())
        return {
            "statusCode": 500,
            "body": json.dumps({"success": False, "error": f"Internal server error: {e}", "results": []}),
        }
