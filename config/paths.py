from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

AGENTS_DIR = ROOT_DIR / "agents"
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
RUNTIME_DIR = ROOT_DIR / "runtime"
RUNTIME_OUTPUTS_DIR = RUNTIME_DIR / "outputs"
RUNTIME_GENERATED_DIR = RUNTIME_DIR / "generated"
RUNTIME_LOGS_DIR = RUNTIME_DIR / "logs"
RUNTIME_CACHE_DIR = RUNTIME_DIR / "cache"

RESEARCH_OUTPUT = RUNTIME_GENERATED_DIR / "research_output.json"
PLAN_OUTPUT = RUNTIME_GENERATED_DIR / "output.json"
ROUTING_DECISION = RUNTIME_GENERATED_DIR / "routing_decision.json"
DIRECT_OUTPUT = RUNTIME_GENERATED_DIR / "direct_output.txt"
PYTHON_OUTPUT = RUNTIME_OUTPUTS_DIR / "output.py"
HTML_OUTPUT = RUNTIME_OUTPUTS_DIR / "output.html"

ROT_CONFIG = AGENTS_DIR / "rot" / "src" / "rot" / "configs" / "config.yml"


def ensure_runtime_dirs() -> None:
    for path in (
        RUNTIME_OUTPUTS_DIR,
        RUNTIME_GENERATED_DIR,
        RUNTIME_LOGS_DIR,
        RUNTIME_CACHE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
