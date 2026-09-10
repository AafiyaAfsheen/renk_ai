# deerflow_agent_function.py
# Fix: returns FULL answer, not truncated. Handles both lanes properly.

import logging
import json
import os
import re
import secrets
import httpx
from pathlib import Path

from pydantic import Field
from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[4]
RESEARCH_OUTPUT = ROOT_DIR / "runtime" / "generated" / "research_output.json"
ROUTING_FILE = ROOT_DIR / "runtime" / "generated" / "routing_decision.json"
DIRECT_OUTPUT = ROOT_DIR / "runtime" / "generated" / "direct_output.txt"

DEFAULT_DEERFLOW_URL = "http://localhost:2026"
DEFAULT_DEERFLOW_OWNER_USER_ID = "renkai"
DEERFLOW_TOKEN_ENV_VAR = "DEERFLOW_INTERNAL_AUTH_TOKEN"


class DeerflowAgentFunctionConfig(FunctionBaseConfig, name="deerflow_agent"):
    llm_name: str = Field(default="nim_llm")
    description: str = Field(default="Lane 1: answers directly. Lane 2: researches for planner.")


@register_function(config_type=DeerflowAgentFunctionConfig)
async def deerflow_agent_function(config: DeerflowAgentFunctionConfig, builder: Builder):

    async def _response_fn(input_message: str) -> str:
        lane, original_input = _read_routing(input_message)
        logger.info(f"[DeerFlow] Lane={lane} | Query={original_input[:80]}")

        result = await _call_deerflow_or_fallback(original_input, lane, builder, config)

        if lane == "deerflow_direct":
            os.makedirs(os.path.dirname(DIRECT_OUTPUT), exist_ok=True)
            with open(DIRECT_OUTPUT, "w", encoding="utf-8") as f:
                f.write(result)
            logger.info(f"[DeerFlow] Direct answer saved ({len(result)} chars)")
            return result

        research_status, research_error = _research_result_status(result)
        os.makedirs(os.path.dirname(RESEARCH_OUTPUT), exist_ok=True)
        with open(RESEARCH_OUTPUT, "w", encoding="utf-8") as f:
            json.dump({
                "query":    original_input,
                "research": result if research_status in {"ready", "fallback"} else "",
                "lane":     "build_pipeline",
                "status":   research_status,
                "error":    research_error,
            }, f, indent=2, ensure_ascii=False)

        if research_status == "failed":
            logger.error("[RENKAI] Research failed: %s", research_error)
            return f"RESEARCH_FAILED: {research_error}. Planner may continue without DeerFlow research."
        if research_status == "fallback":
            logger.warning("[RENKAI] Research unavailable; NIM fallback recorded")
            return "RESEARCH_FALLBACK: NIM research saved. Planner can proceed."

        logger.info("[RENKAI] Research succeeded; Planner ready")
        return "RESEARCH_READY: DeerFlow complete. Planner can proceed."

    yield FunctionInfo.create(
        single_fn=_response_fn,
        description=config.description
    )


def _read_routing(fallback_input: str):
    try:
        with open(ROUTING_FILE, "r", encoding="utf-8") as f:
            r = json.load(f)
        return r.get("lane", "deerflow_direct"), r.get("original_input", fallback_input)
    except Exception:
        return "deerflow_direct", fallback_input


def _research_result_status(result: str) -> tuple[str, str | None]:
    """Classify a DeerFlow research result before persisting planner context."""
    if result.startswith("[RENKAI] DeerFlow unavailable; NIM fallback used."):
        return "fallback", "DeerFlow unavailable; NIM fallback used"
    if result.startswith("[RENKAI] DeerFlow API error"):
        match = re.search(r"HTTP (\d+)", result)
        detail = f"DeerFlow HTTP {match.group(1)}" if match else "DeerFlow API error"
        return "failed", detail
    if result.startswith("[RENKAI] DeerFlow authentication failed"):
        return "failed", "DeerFlow authentication failed"
    return "ready", None


async def _call_deerflow_or_fallback(query: str, lane: str, builder, config) -> str:
    task = query if lane == "deerflow_direct" else (
        f"Research this software build request thoroughly: {query}. "
        "Return: best libraries, architecture patterns, implementation steps, key considerations."
    )

    deerflow_url = os.getenv("DEERFLOW_URL", DEFAULT_DEERFLOW_URL).rstrip("/")
    internal_token = os.getenv(DEERFLOW_TOKEN_ENV_VAR)
    owner_user_id = os.getenv("DEERFLOW_OWNER_USER_ID", DEFAULT_DEERFLOW_OWNER_USER_ID)

    if not internal_token:
        logger.error("[RENKAI] DeerFlow authentication failed: %s is not set", DEERFLOW_TOKEN_ENV_VAR)
        return f"[RENKAI] DeerFlow authentication failed: {DEERFLOW_TOKEN_ENV_VAR} is not configured."

    # The current DeerFlow Gateway applies CSRF middleware before Internal Auth.
    # It requires a double-submit pair even for trusted backend callers: the
    # cookie and header values must be identical. This is generated anew for
    # every backend request and is never logged.
    csrf_token = secrets.token_urlsafe(48)
    headers = {
        "Content-Type": "application/json",
        "X-DeerFlow-Internal-Token": internal_token,
        "X-DeerFlow-Owner-User-Id": owner_user_id,
        "X-CSRF-Token": csrf_token,
        "Cookie": f"csrf_token={csrf_token}",
    }
    payload = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "user", "content": task}]},
    }

    try:
        logger.info("[RENKAI] DeerFlow request started")
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
            response = await client.post(f"{deerflow_url}/api/runs/wait", headers=headers, json=payload)
    except httpx.RequestError as exc:
        logger.warning("[RENKAI] DeerFlow unavailable: %s", exc)
        fallback = await _nim_fallback(query, lane, builder, config)
        return "[RENKAI] DeerFlow unavailable; NIM fallback used.\n\n" + fallback

    if response.status_code in {401, 403}:
        logger.error("[RENKAI] DeerFlow authentication failed: HTTP %s", response.status_code)
        return f"[RENKAI] DeerFlow authentication failed (HTTP {response.status_code})."
    if response.status_code != 200:
        logger.error("[RENKAI] DeerFlow API error: HTTP %s", response.status_code)
        return f"[RENKAI] DeerFlow API error (HTTP {response.status_code}): {_response_detail(response)}"

    try:
        data = response.json()
    except json.JSONDecodeError:
        logger.error("[RENKAI] DeerFlow API error: invalid JSON response")
        return "[RENKAI] DeerFlow API error: Gateway returned invalid JSON."

    content = _extract_assistant_content(data)
    if content:
        logger.info("[RENKAI] DeerFlow request succeeded")
        return content

    logger.error("[RENKAI] DeerFlow API error: no assistant message in response")
    return "[RENKAI] DeerFlow API error: Gateway response contained no assistant message."


def _response_detail(response: httpx.Response) -> str:
    """Return a concise, non-secret error detail from a Gateway response."""
    try:
        detail = response.json().get("detail", response.text)
    except (json.JSONDecodeError, AttributeError):
        detail = response.text
    return str(detail)[:500]


def _extract_assistant_content(data: object) -> str | None:
    """Extract the final assistant message from DeerFlow's current wait response."""
    if not isinstance(data, dict):
        return None
    messages = data.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant" and message.get("type") != "ai":
            continue
        content = _normalise_message_content(message.get("content"))
        if content:
            return content
    return None


def _normalise_message_content(content: object) -> str:
    """Handle both string and structured LangChain/OpenAI-style message content."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                parts.append(text)
    return " ".join(parts)


async def _nim_fallback(query: str, lane: str, builder, config) -> str:
    try:
        llm = await builder.get_llm(
            llm_name=config.llm_name,
            wrapper_type=LLMFrameworkEnum.LANGCHAIN
        )

        if lane == "deerflow_direct":
            prompt = f"""Answer this request fully and thoroughly. Use markdown formatting.
Use ## for sections, ### for subsections, **bold** for key terms, bullet lists where appropriate.
Give a COMPLETE answer — do not truncate or summarize.

USER REQUEST: {query}

Provide the full detailed answer now:"""
        else:
            prompt = f"""Research this software build request and return structured findings.

BUILD REQUEST: {query}

Cover:
- Best Python libraries/frameworks to use
- Recommended architecture
- Key implementation steps  
- Important considerations and gotchas"""

        resp = await llm.ainvoke(prompt)
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:
        logger.warning("[DeerFlow] NIM fallback failed; using deterministic offline guidance: %s", exc)
        if lane == "deerflow_direct":
            return (
                f"This request is best answered directly without external model access.\n\n"
                f"User request: {query}\n\n"
                "Key idea: explain the concept clearly, define the core components, provide a simple example, and note practical uses."
            )
        return (
            f"Offline build guidance for: {query}\n\n"
            "Recommended approach: choose a small Python CLI or single-file app, keep the logic in standard-library functions, validate inputs, print readable output, and test against a few sample cases."
        )
