import logging
import os
import json
import re
from pathlib import Path

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[4]
ROUTING_FILE = ROOT_DIR / "runtime" / "generated" / "routing_decision.json"
RESEARCH_FILE = ROOT_DIR / "runtime" / "generated" / "research_output.json"
PLAN_FILE = ROOT_DIR / "runtime" / "generated" / "output.json"


class PlannerAgentConfig(FunctionBaseConfig, name="planner_agent"):
    llm_name: LLMRef = Field(description="LLM to use for planning")


class AgentRequirements(BaseModel):
    agent_type:       str
    primary_purpose:  str
    key_capabilities: list
    target_domain:    str


def planner_failure_payload(reason: str) -> dict:
    return {
        "status": "failed",
        "reason": f"PLANNER FAILED: {reason}",
        "project": "Error",
        "algorithm_steps": [],
    }


def build_fallback_plan(user_input: str) -> dict:
    prompt = str(user_input or "").lower()
    html_keywords = [
        "html", "web app", "website", "webpage", "frontend", "ui", "interface",
        "game", "tic tac", "chess", "rummy", "browser", "visual", "dashboard",
        "canvas", "interactive", "chart", "form"
    ]
    python_keywords = [
        "python", "script", "program", "algorithm", "solver", "calculator",
        "prime", "factorial", "sum", "parse", "data processing", "generate code",
        "number", "math", "logic", "analysis", "automation"
    ]
    is_html = any(k in prompt for k in html_keywords) and not any(k in prompt for k in python_keywords)
    output_type = "html" if is_html else "python"
    project_name = "Python CLI Program" if output_type == "python" else "Interactive Web App"
    steps = [
        {
            "step_number": 1,
            "step_title": "Clarify requirements",
            "step_description": "Identify the core input, output, and validation rules for the project.",
            "instructions": [
                "Read the user request and convert it into concrete requirements.",
                "Define the expected inputs, constraints, and success conditions."
            ],
            "inputs": [],
            "outputs": [],
            "dependencies": {"requires_previous_steps": [], "provides_for_next_steps": [2]}
        },
        {
            "step_number": 2,
            "step_title": "Implement the logic",
            "step_description": "Build the main feature logic using the standard library and clear functions.",
            "instructions": [
                "Write the core algorithm or app behavior in a single file.",
                "Keep code modular and free of external dependencies." 
            ],
            "inputs": [],
            "outputs": [],
            "dependencies": {"requires_previous_steps": [1], "provides_for_next_steps": [3]}
        },
        {
            "step_number": 3,
            "step_title": "Validate the result",
            "step_description": "Check the generated implementation for correctness and output readability.",
            "instructions": [
                "Run the program or validate the behavior against sample inputs.",
                "Ensure the output is printed clearly and the program exits cleanly."
            ],
            "inputs": [],
            "outputs": [],
            "dependencies": {"requires_previous_steps": [2], "provides_for_next_steps": []}
        }
    ]
    return {
        "project": project_name,
        "output_type": output_type,
        "algorithm_steps": steps,
    }


def enforce_semantic_output_type(user_input: str, plan: dict) -> dict:
    if not isinstance(plan, dict):
        return plan
    lower_input = str(user_input or "").lower()
    python_intent = any(k in lower_input for k in [
        "prime", "factorial", "fibonacci", "calculator", "sum", "average", "parse",
        "algorithm", "solver", "script", "python", "number", "math", "logic",
        "generate", "sort", "search", "find", "analyze"
    ])
    html_intent = any(k in lower_input for k in [
        "html", "website", "web app", "webpage", "dashboard", "frontend", "ui",
        "interface", "game", "canvas", "interactive", "visualization", "form"
    ])

    if python_intent and not html_intent:
        plan["output_type"] = "python"
    elif html_intent and not python_intent:
        plan["output_type"] = "html"

    if "prime" in lower_input or "factorial" in lower_input:
        plan["output_type"] = "python"
    return plan


def is_valid_plan(plan: object) -> bool:
    if not isinstance(plan, dict):
        return False
    if plan.get("status") == "failed":
        return False
    project = str(plan.get("project", "")).strip()
    output_type = str(plan.get("output_type", "")).strip().lower()
    algorithm_steps = plan.get("algorithm_steps")
    if not project or project.lower() == "error":
        return False
    if output_type not in {"python", "html"}:
        return False
    if not isinstance(algorithm_steps, list) or not algorithm_steps:
        return False
    if not any(isinstance(step, dict) and isinstance(step.get("instructions"), list) and step["instructions"] for step in algorithm_steps):
        return False
    return True


def extract_json(text: str) -> dict:
    text = re.sub(r"```json|```", "", text).strip()
    text = re.sub(r"\u2011|\u2013|\u2014", "-", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found")
    raw = match.group(0)

    cleaned = raw
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    cleaned = re.sub(r'(?<=\})\s*(?=\{)', ', ', cleaned)
    cleaned = re.sub(r'(?<=\])\s*(?=\{)', ', ', cleaned)
    cleaned = re.sub(r'(?<=\d)\s+(?=\"[A-Za-z_])', ' ', cleaned)

    for candidate in (cleaned, raw):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError("Planner output could not be parsed as valid JSON")


async def llm_json_call(llm, prompt: str, model: type):
    for _ in range(3):
        resp    = await llm.ainvoke(prompt)
        content = resp.content if hasattr(resp, "content") else str(resp)
        if content.strip():
            data = extract_json(content)
            return model(**data)
    raise ValueError("LLM returned empty response")


def get_routing_lane() -> str:
    try:
        with open(ROUTING_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("lane", "build_pipeline")
    except Exception:
        return "build_pipeline"


def load_research_context() -> str:
    try:
        with open(RESEARCH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("status") in {"ready", "fallback"}:
            return data.get("research", "")
    except Exception:
        pass
    return ""


@register_function(config_type=PlannerAgentConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def planner_agent(tool_config: PlannerAgentConfig, builder: Builder):

    llm = await builder.get_llm(
        llm_name=tool_config.llm_name,
        wrapper_type=LLMFrameworkEnum.LANGCHAIN
    )

    async def _arun(user_input: str) -> str:
        if get_routing_lane() != "build_pipeline":
            logger.info("[Planner] Skipping — not build_pipeline lane")
            return json.dumps({"skipped": True})

        try:
            logger.info("[Planner] Starting...")
            research_context = load_research_context()

            lower_input = user_input.lower()
            html_keywords = [
                "html", "web app", "website", "webpage", "frontend", "ui", "interface",
                "game", "tic tac", "chess", "rummy", "browser", "visual", "dashboard",
                "canvas", "interactive", "chart", "form"
            ]
            python_keywords = [
                "python", "script", "program", "algorithm", "solver", "calculator",
                "prime", "factorial", "sum", "parse", "data processing", "generate code",
                "number", "math", "logic", "analysis", "automation"
            ]
            is_html = any(k in lower_input for k in html_keywords) and not any(k in lower_input for k in python_keywords)
            explicit_python = any(k in lower_input for k in python_keywords)
            if is_html:
                output_rule = "- Output: a single self-contained HTML file with inline CSS and JS"
                code_rules  = """
CRITICAL CODE RULES:
- Output must be a SINGLE HTML FILE with everything inline
- Must be interactive and fully functional
- Dark modern UI, no external dependencies except CDN
- NO placeholder text or fake data"""
            else:
                output_rule = "- Output: a single Python file that prints all results to stdout"
                code_rules  = """
CRITICAL CODE RULES:
- Use ONLY Python standard library (math, random, collections, datetime, json, re, string, itertools, functools)
- NO tkinter, pygame, or ANY GUI framework
- NO requests, urllib, httpx, or ANY network calls  
- NO sqlite3 or databases
- NO placeholder API keys
- ALL output must use print() — user sees ONLY what is printed
- The script must run completely in under 30 seconds
- Must produce visible printed output the user can read"""

            plan_prompt = f"""Design a build plan for this project.

USER REQUEST: {user_input}

RESEARCH CONTEXT:
{research_context or "No research context available."}

PROJECT TYPE: {"HTML/Web" if is_html else "Python CLI"}
{output_rule}

{code_rules}

Return ONLY valid JSON with this exact structure and nothing else.
{{
  "project": "short project name",
  "output_type": "{'html' if is_html else 'python'}",
  "algorithm_steps": [
    {{
      "step_number": 1,
      "step_title": "...",
      "step_description": "...",
      "instructions": [
        "specific implementation instruction 1",
        "specific implementation instruction 2"
      ],
      "inputs": [],
      "outputs": [],
      "dependencies": {{
        "requires_previous_steps": [],
        "provides_for_next_steps": []
      }}
    }}
  ]
}}

Rules:
- 4 steps maximum
- Each instruction must be specific and implementable
- No markdown, no prose, no comments, no trailing commas
- Use double quotes for all keys and string values
- For Python: last step must include "Call main() and print all results"
- Output must be parseable by json.loads() immediately
"""
            try:
                resp    = await llm.ainvoke(plan_prompt)
                content = resp.content if hasattr(resp, "content") else str(resp)
                plan    = extract_json(content)
            except Exception as e:
                logger.warning("[Planner] LLM parse failed; using deterministic fallback plan: %s", e)
                plan = build_fallback_plan(user_input)

            if not is_html and plan.get("output_type", "").lower() not in {"python", ""}:
                plan["output_type"] = "python"
            if is_html and plan.get("output_type", "").lower() not in {"html", ""}:
                plan["output_type"] = "html"
            if not is_html and explicit_python:
                plan["output_type"] = "python"

            plan = enforce_semantic_output_type(user_input, plan)

            if not is_valid_plan(plan):
                logger.warning("[Planner] invalid LLM plan, using deterministic fallback plan")
                plan = build_fallback_plan(user_input)
                plan = enforce_semantic_output_type(user_input, plan)

            if not is_valid_plan(plan):
                raise ValueError(f"Planner returned invalid plan payload: {json.dumps(plan, ensure_ascii=False)[:400]}")

            if "project" not in plan:
                plan["project"] = user_input[:40]
            if not plan.get("algorithm_steps"):
                raise ValueError("Plan missing algorithm_steps")

            os.makedirs(os.path.dirname(PLAN_FILE), exist_ok=True)
            with open(PLAN_FILE, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2)

            logger.info(f"[Planner] Plan saved — {len(plan['algorithm_steps'])} steps, type={plan.get('output_type','?')}")
            return json.dumps(plan, indent=2)

        except Exception as e:
            failure = planner_failure_payload(str(e))
            logger.error(f"[Planner] Failed: {e}", exc_info=True)
            os.makedirs(os.path.dirname(PLAN_FILE), exist_ok=True)
            with open(PLAN_FILE, "w", encoding="utf-8") as f:
                json.dump(failure, f, indent=2)
            return json.dumps(failure, indent=2)

    yield FunctionInfo.from_fn(
        _arun,
        description="Planner — creates a build blueprint with strict CLI/HTML output rules"
    )
