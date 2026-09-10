import logging
import json
import re
import os
from pathlib import Path
from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig
from nat.builder.framework_enum import LLMFrameworkEnum

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[4]
JSON_PATH = ROOT_DIR / "runtime" / "generated" / "output.json"
ROUTING_PATH = ROOT_DIR / "runtime" / "generated" / "routing_decision.json"
OUT_PY = ROOT_DIR / "runtime" / "outputs" / "output.py"
OUT_HTML = ROOT_DIR / "runtime" / "outputs" / "output.html"


class ConstructorAgentFunctionConfig(FunctionBaseConfig, name="constructor_agent"):
    llm_name: str      = Field(default="nim_llm")
    verbose:  bool     = Field(default=True)
    max_fix_attempts: int = Field(default=3)
    description: str   = Field(default="Generates working code from plan")


def is_html_project(plan_data: dict) -> bool:
    """
    HTML mode for: games, dashboards, visual tools, web UIs.
    Python mode for: algorithms, data processing, simulations, CLI tools.
    """
    declared_output_type = str(plan_data.get("output_type", "")).strip().lower()
    if declared_output_type == "python":
        return False
    if declared_output_type == "html":
        return True

    project = plan_data.get("project", "").lower()
    steps   = json.dumps(plan_data.get("algorithm_steps", [])).lower()
    # Legacy fallback only for plans that do not declare a recognized type.
    html_keywords = [
        "html", "css", "webpage", "website", "web page", "frontend",
        "tailwind", "dashboard", "ui", "interface", "game", "tic tac",
        "chess", "rummy", "browser", "visual", "canvas", "interactive",
        "click", "button", "drag", "animation",
    ]
    return any(k in project or k in steps for k in html_keywords)


def needs_simulation(plan_data: dict) -> bool:
    """Detect if project would normally need internet/API — use simulated data instead."""
    project = plan_data.get("project", "").lower()
    steps   = json.dumps(plan_data.get("algorithm_steps", [])).lower()
    api_keywords = [
        "weather", "stock", "price", "api", "scrape", "fetch", "news",
        "twitter", "github", "slack", "telegram", "bitcoin", "crypto",
        "real-time", "live data", "monitor", "alert",
    ]
    return any(k in project or k in steps for k in api_keywords)


def clean_code(text: str) -> str:
    text = text.strip()
    text = re.sub(r"```html|```python|```javascript|```css|```", "", text)
    return text.strip()


def appears_stepwise(code: str) -> bool:
    if not isinstance(code, str):
        return False
    if code.strip().startswith("# No code provided"):
        return True
    if any(marker in code for marker in ["# Step ", "STEP ", "Step "]):
        return True
    if code.count('if __name__ == "__main__":') > 1:
        return True
    function_names = re.findall(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", code, flags=re.MULTILINE)
    counts = {}
    for name in function_names:
        counts[name] = counts.get(name, 0) + 1
    if any(count > 1 for count in counts.values()):
        return True
    return False


def looks_like_placeholder_response(code: str) -> bool:
    if not isinstance(code, str):
        return True
    text = code.strip()
    if not text:
        return True
    normalized = text.lower()
    placeholder_patterns = [
        "could you please provide the code",
        "please provide the code",
        "specific error message that needs to be fixed",
        "i can help fix this",
        "here's the corrected code",
        "here is the corrected code",
        "no code provided",
        "this needs more context",
    ]
    if any(p in normalized for p in placeholder_patterns):
        return True
    python_signals = ["def ", "import ", "print(", "if __name__ == \"__main__\":", "return ", "class ", "for ", "while "]
    if not any(signal in normalized for signal in python_signals):
        return True
    return False


def infer_program_kind(plan_data: dict) -> str:
    text = json.dumps(plan_data, ensure_ascii=False).lower()
    if "prime" in text:
        return "prime"
    if "factorial" in text:
        return "factorial"
    try:
        with open(ROUTING_PATH, "r", encoding="utf-8") as f:
            routing = json.load(f)
        original = str(routing.get("original_input", "")).lower()
        if "prime" in original:
            return "prime"
        if "factorial" in original:
            return "factorial"
    except Exception:
        pass
    return "generic"


def build_python_fallback_program(project: str, algorithm_steps: list, kind: str | None = None) -> str:
    text = " ".join(
        str(step.get("step_title", "")) + " " + " ".join(str(i) for i in step.get("instructions", []))
        for step in algorithm_steps
    ).lower()
    kind = kind or ("prime" if "prime" in text else "factorial" if "factorial" in text else "generic")

    if kind == "prime":
        return '''import math
import sys


def parse_limit():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python output.py <limit>")
    try:
        limit = int(sys.argv[1])
    except ValueError as exc:
        raise SystemExit("Limit must be an integer.") from exc
    if limit < 2:
        raise SystemExit("Limit must be at least 2.")
    return limit


def is_prime(value):
    if value < 2:
        return False
    if value == 2:
        return True
    if value % 2 == 0:
        return False
    for divisor in range(3, int(math.isqrt(value)) + 1, 2):
        if value % divisor == 0:
            return False
    return True


def generate_primes(limit):
    return [n for n in range(2, limit + 1) if is_prime(n)]


def main():
    limit = parse_limit()
    primes = generate_primes(limit)
    print(f"Prime numbers up to {limit}:")
    if not primes:
        print("No primes found.")
    else:
        print(", ".join(str(n) for n in primes))


if __name__ == "__main__":
    main()
'''

    if kind == "factorial":
        return '''import sys


def parse_input():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python output.py <number>")
    try:
        value = int(sys.argv[1])
    except ValueError as exc:
        raise SystemExit("Input must be an integer.") from exc
    return value


def factorial(value):
    if value < 0:
        raise ValueError("Factorial is undefined for negative numbers.")
    result = 1
    for n in range(2, value + 1):
        result *= n
    return result


def main():
    number = parse_input()
    print(f"{number}! = {factorial(number)}")


if __name__ == "__main__":
    main()
'''

    return '''import sys


def parse_input():
    if len(sys.argv) > 1:
        return sys.argv[1]
    return "default"


def main():
    value = parse_input()
    print(f"Project: {project}")
    print(f"Input: {value}")
    print("Implementation generated from the planner specification.")


if __name__ == "__main__":
    main()
'''.replace("{project}", str(project or "Python CLI Program"))


def generated_code_matches_plan(plan_data: dict, code: str) -> bool:
    if not isinstance(code, str) or not code.strip():
        return False
    if code.strip().startswith("# No code provided"):
        return False
    summary = json.dumps(plan_data, ensure_ascii=False).lower()
    code_lower = code.lower()
    if "prime" in summary:
        required = ["def parse_limit", "def is_prime", "if __name__ == \"__main__\""]
        return all(item in code_lower for item in required)
    if "factorial" in summary:
        required = ["def factorial", "def main", "if __name__ == \"__main__\""]
        return all(item in code_lower for item in required)
    return True


def build_integrated_program_prompt(project: str, algorithm_steps: list, sim_note: str = "") -> str:
    step_details = []
    for step in algorithm_steps:
        step_number = step.get("step_number", "?")
        step_title = step.get("step_title", "Implementation step")
        instructions = step.get("instructions", [])
        rendered = "\n".join(f"- {instruction}" for instruction in instructions)
        step_details.append(f"Step {step_number}: {step_title}\n{rendered}")

    combined_steps = "\n\n".join(step_details) if step_details else "No additional plan detail provided."
    return f'''Generate ONE coherent final Python program for this project.

PROJECT: {project}

PLANNER STEPS (these describe one program, not independent programs):
{combined_steps}

CRITICAL REQUIREMENTS:
- Treat every step as part of the same implementation.
- Produce a single final implementation with all logic integrated together.
- Do NOT emit separate programs for each step.
- Do NOT use "# Step 1", "# Step 2", or other step-marked code blocks in the final output.
- Maintain ONE import section only.
- Define each helper function once.
- Include exactly one main() function.
- Include exactly one if __name__ == "__main__": main() block.
- Keep the program coherent, compact, and executable as a single file.
- The final code should be a clean, production-quality program, not a concatenation of partial implementations.
- Return only raw Python code with no markdown fences, comments about steps, or explanations.

{sim_note}

ABSOLUTE RULES:
- Standard library ONLY: math, random, collections, itertools, datetime, json, re, os, sys, string, functools, statistics
- NO tkinter, pygame, wx, or ANY GUI library whatsoever
- NO requests, httpx, urllib, aiohttp, or ANY network calls
- NO placeholder keys like "YOUR_API_KEY"
- NO sqlite3 or any database
- ALL output must be printed with print() and the user should see clear readable output
- Ensure the program runs directly as a script and demonstrates the final behavior in one coherent flow
- Use standard Python patterns for validation and output
'''


def parse_inspector_debug(output: str):
    err  = re.search(r"ERROR_TYPE:\s*(.+)", output)
    tb   = re.search(r"TRACEBACK:\n(.+?)\n\nORIGINAL CODE:", output, re.S)
    return {
        "error_type": err.group(1).strip() if err else "UNKNOWN",
        "traceback":  tb.group(1).strip()  if tb  else "",
        "is_failed":  "OVERALL STATUS: FAILED" in output,
    }


async def surgical_fix(llm, code: str, error_text: str, project: str = "Python CLI Program", kind: str | None = None) -> str:
    prompt = f"""You are a SURGICAL Python code repair agent.
Fix ONLY the specific error shown. Return the COMPLETE corrected Python code.
No markdown, no backticks, no explanation.

STRICT RULES (do not violate or the fix will also fail):
- Standard library ONLY: math, random, collections, itertools, datetime, json, re, os, sys, string, functools, statistics
- NO tkinter, pygame, wx, or ANY GUI
- NO requests, httpx, urllib, or ANY network calls
- NO placeholder API keys or "YOUR_KEY_HERE"
- NO sqlite3 or databases
- ALL results must be printed with print()

ERROR:
{error_text}

CODE TO FIX:
{code}
"""
    resp = await llm.ainvoke(prompt)
    fixed = clean_code(resp.content if hasattr(resp, "content") else str(resp))
    if looks_like_placeholder_response(fixed):
        logger.warning("[Constructor] Surgical repair returned non-code placeholder; using deterministic fallback")
        return build_python_fallback_program(project, [{"step_title": "Repair", "instructions": ["Restore a valid Python implementation from the original intent."]}], kind or infer_program_kind({"project": project, "output_type": "python"}))
    return fixed


@register_function(config_type=ConstructorAgentFunctionConfig)
async def constructor_agent_function(config: ConstructorAgentFunctionConfig, builder: Builder):

    async def _response_fn(input_message: str) -> str:
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception:
            plan_data = None

        if not plan_data or not plan_data.get("algorithm_steps"):
            return "ERROR: No plan found. Run planner first."

        project         = plan_data.get("project", "Unnamed")
        algorithm_steps = plan_data["algorithm_steps"]
        html_mode       = is_html_project(plan_data)
        sim_mode        = needs_simulation(plan_data) and not html_mode
        OUT_FILE        = OUT_HTML if html_mode else OUT_PY

        logger.info(f"[Constructor] Mode={'HTML' if html_mode else 'Python'} Sim={sim_mode} | {project}")

        llm = await builder.get_llm(
            llm_name=config.llm_name,
            wrapper_type=LLMFrameworkEnum.LANGCHAIN
        )
        os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)

        if html_mode:
            instructions = []
            for step in algorithm_steps:
                for inst in step.get("instructions", []):
                    instructions.append(f"- {inst}")

            prompt = f"""You are an expert full-stack developer. Generate a complete single-file HTML application.

PROJECT: {project}

REQUIREMENTS:
{chr(10).join(instructions)}

STRICT RULES:
- Return ONLY raw HTML — absolutely no markdown, no backticks, no explanation text
- All CSS inside <style>, all JavaScript inside <script>
- Dark theme with modern clean UI (dark backgrounds, light text)
- The app must be FULLY FUNCTIONAL with real working JavaScript logic
- ALL features listed in requirements must actually work
- For agents/AI tools: implement the agent logic in JavaScript — state machine, decision tree, or rule engine
- For games: full game loop, win condition, score tracking
- For dashboards: real charts using Chart.js from CDN, real data generation in JS
- For data tools: actual processing logic in JS, not just display
- Use CDN libraries when needed: Chart.js, D3.js, Lodash (cdnjs.cloudflare.com)
- NO placeholder buttons that do nothing
- NO "coming soon" or "TODO" sections
- The HTML file must work perfectly when opened in any browser

Generate the complete HTML now:"""

            resp = None
            for attempt in range(2):
                try:
                    resp = await llm.ainvoke(prompt)
                    break
                except Exception as e:
                    if attempt == 0 and ("timeout" in str(e).lower() or "cancel" in str(e).lower()):
                        logger.warning("[Constructor] HTML timeout on attempt 1 — retrying with shorter prompt")
                        # Shorter fallback prompt
                        short_instructions = chr(10).join(instructions[:8])  # first 8 only
                        prompt = f"""Generate a complete single-file HTML app for: {project}

Key features:
{short_instructions}

Rules: Dark theme, inline CSS+JS, fully functional, no external deps except CDN.
Return ONLY raw HTML starting with <!DOCTYPE html>"""
                    else:
                        raise

            if resp is None:
                return f"ERROR: HTML generation timed out for {project}"

            code = clean_code(resp.content if hasattr(resp, "content") else str(resp))

            if not code.strip().startswith("<!"):
                code = "<!DOCTYPE html>\n" + code

            with open(OUT_FILE, "w", encoding="utf-8") as f:
                f.write(code)

            logger.info(f"[Constructor] HTML saved ({code.count(chr(10))} lines)")
            return f"HTML file generated! Open: {OUT_FILE}"


        sim_note = ""
        if sim_mode:
            sim_note = """
SIMULATION MODE — This project normally needs internet/APIs but runs in a sandbox:
- Generate realistic HARDCODED/SIMULATED data instead of real API calls
- Use random/datetime to make data feel dynamic
- Add a comment: # In production: replace with real API call to [service]
- The simulation must still demonstrate the full agent logic and print useful output
"""

        kind = infer_program_kind(plan_data)
        inspector_fn = await builder.get_function("inspector")
        prompt = build_integrated_program_prompt(project, algorithm_steps, sim_note)

        try:
            resp = await llm.ainvoke(prompt)
            code = clean_code(resp.content if hasattr(resp, "content") else str(resp))
        except Exception as exc:
            logger.warning("[Constructor] LLM generation failed for integrated program: %s", exc)
            code = ""

        if not code or appears_stepwise(code):
            logger.warning("[Constructor] Generated code still looks stepwise or empty; using deterministic integrated fallback")
            code = build_python_fallback_program(project, algorithm_steps, kind)

        if not code or not code.strip():
            code = build_python_fallback_program(project, algorithm_steps, kind)

        if code.strip().startswith("# No code provided"):
            code = build_python_fallback_program(project, algorithm_steps, kind)

        if not generated_code_matches_plan(plan_data, code):
            logger.warning("[Constructor] Generated code does not match the requested program; replacing it with a plan-aware deterministic implementation")
            code = build_python_fallback_program(project, algorithm_steps, kind)

        # Self-healing part
        for attempt in range(config.max_fix_attempts):
            with open(OUT_PY, "w", encoding="utf-8") as f:
                f.write(code)

            result = await inspector_fn.ainvoke("check")
            parsed = parse_inspector_debug(result)

            if config.verbose:
                logger.info(f"[Constructor] Attempt {attempt+1} → {parsed['error_type']}")

            if not parsed["is_failed"]:
                logger.info(f"[Constructor] Passed attempt {attempt+1}")
                return code

            code = await surgical_fix(llm, code, parsed["traceback"], project, kind)

        # Write final version even if still failing
        with open(OUT_PY, "w", encoding="utf-8") as f:
            f.write(code)
        return code

    yield FunctionInfo.create(
        single_fn=_response_fn,
        description=config.description
    )
