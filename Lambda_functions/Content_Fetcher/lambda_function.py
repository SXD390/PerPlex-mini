#!/usr/bin/env python3
import os
import re
import json
import time
import asyncio
import logging
import traceback
from typing import Dict, Any
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

# ---- Logging setup ----
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("lambda-fetch")

# ---- Configs ----
DEFAULT_TIMEOUT_MS = int(os.getenv("FETCH_TIMEOUT_MS", "30000"))

CHROME_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--no-zygote",
    "--single-process",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-features=VizDisplayCompositor",
    "--disable-blink-features=AutomationControlled",
    "--disable-web-security",
    "--window-size=1200,800",
    "--font-cache-shared-handle=0",
    "--use-gl=swiftshader",
]

SELECTORS = [
    "main","article",'[role=\"main\"]',".content",".post-content",
    ".entry-content","#content",".main-content",".article-content",
    ".post-body",".entry-body",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

def to_markdown_like(title: str, content: str, url: str) -> str:
    if not content:
        return ""
    content = re.sub(r"\s+", " ", content).strip()
    md = f"# {title}\n\n**Source:** {url}\n\n---\n\n"
    out = []
    for raw in content.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if len(line) > 100 and not line.startswith("#"):
            out.append(f"{line}\n")
        elif line.isupper() and len(line) < 50:
            out.append(f"## {line}\n")
        else:
            out.append(f"{line}\n")
    md += "\n".join(out)
    if len(md) > 50000:
        md = md[:50000] + "\n\n... (content truncated)"
    return md

async def run_fetch(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> Dict[str, Any]:
    # Ensure caches are writable in Lambda
    os.environ.setdefault("HOME", "/tmp")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
    os.makedirs("/tmp/.cache/fontconfig", exist_ok=True)

    t0 = time.time()
    log.info("fetch:start url=%s timeout_ms=%s", url, timeout_ms)
    log.debug("playwright args: %s", CHROME_ARGS)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=CHROME_ARGS)
        try:
            context = await browser.new_context(
                viewport={"width": 1200, "height": 800},
                user_agent=USER_AGENT,
            )
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)

            # Page events
            page.on("console", lambda msg: log.debug("page.console: %s", msg.text()))
            page.on("pageerror", lambda err: log.warning("page.error: %s", err))

            # Navigate (with one quick retry)
            for attempt in (1, 2):
                try:
                    t_nav0 = time.time()
                    log.info("fetch:goto attempt=%d %s", attempt, url)
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    log.info("fetch:goto:done attempt=%d elapsed_ms=%d",
                             attempt, int((time.time()-t_nav0)*1000))
                    break
                except Exception as e:
                    log.warning("fetch:goto failed attempt=%d err=%s", attempt, e)
                    if attempt == 2:
                        raise

            # Title (use DOM to avoid Page.title() shadowing issues)
            t_title0 = time.time()
            title = await page.evaluate("() => document.title || ''")
            log.info("fetch:title '%s' (elapsed_ms=%d)",
                     title, int((time.time()-t_title0)*1000))

            # Extract content
            content = ""
            chosen = None
            for sel in SELECTORS:
                try:
                    el = page.locator(sel).first
                    cnt = await el.count()
                    log.info("fetch:probe selector=%s count=%s", sel, cnt)
                    if cnt:
                        content = await el.inner_text()
                        if content.strip():
                            chosen = sel
                            break
                except Exception as e:
                    log.debug("fetch:selector error sel=%s err=%s", sel, e)

            if not content.strip():
                try:
                    body = page.locator("body")
                    content = await body.inner_text()
                    chosen = "body"
                except Exception as e:
                    log.warning("fetch:body failed err=%s", e)
                    content = ""

            md = to_markdown_like(title, content or "", url)
            preview = (md[:100].replace("\n", " ") if md else "")
            log.info("fetch:content chosen=%s text_len=%d md_len=%d md_preview='%s...'",
                     chosen, len(content or ""), len(md), preview)

            result = {
                "success": True,
                "title": title,
                "markdown_content": md,
                "url": url,
                "content_length": len(md),
                "error": None,
            }
            log.info("fetch:success content_length=%d total_elapsed_ms=%d",
                     len(md), int((time.time()-t0)*1000))
            return result

        except PWTimeoutError as e:
            log.error("fetch:timeout url=%s err=%s", url, e)
            return {
                "success": False,
                "title": "",
                "markdown_content": "",
                "url": url,
                "content_length": 0,
                "error": f"Timeout: {e}",
            }
        except Exception as e:
            log.error("fetch:exception url=%s err=%s\n%s", url, e, traceback.format_exc())
            return {
                "success": False,
                "title": "",
                "markdown_content": "",
                "url": url,
                "content_length": 0,
                "error": str(e),
            }
        finally:
            try:
                await browser.close()
                log.debug("fetch:browser closed")
            except Exception as e:
                log.debug("fetch:browser close error: %s", e)

def lambda_handler(event, context):
    req_id = getattr(context, "aws_request_id", "n/a")
    log.info("handler:start request_id=%s eventKeys=%s", req_id, list((event or {}).keys()))
    try:
        url = (event or {}).get("url", "").strip()
        if not url:
            log.warning("validation:url missing")
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "success": False,
                    "title": "",
                    "markdown_content": "",
                    "url": "",
                    "content_length": 0,
                    "error": "URL parameter is required",
                }),
            }

        if not (url.startswith("http://") or url.startswith("https://")):
            log.warning("validation:url invalid url=%s", url)
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "success": False,
                    "title": "",
                    "markdown_content": "",
                    "url": url,
                    "content_length": 0,
                    "error": "Invalid URL format",
                }),
            }

        timeout_ms = int(os.getenv("FETCH_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS)))
        result = asyncio.run(run_fetch(url, timeout_ms=timeout_ms))
        log.info("handler:done request_id=%s success=%s content_length=%s",
                 req_id, result.get("success"), result.get("content_length"))
        return {"statusCode": 200, "body": json.dumps(result)}

    except Exception as e:
        log.error("handler:exception request_id=%s err=%s\n%s", req_id, e, traceback.format_exc())
        return {
            "statusCode": 500,
            "body": json.dumps({
                "success": False,
                "title": "",
                "markdown_content": "",
                "url": (event or {}).get("url", ""),
                "content_length": 0,
                "error": f"Internal server error: {e}",
            }),
        }
