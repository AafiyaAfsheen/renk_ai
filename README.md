# Renkai

Renkai is a multi-agent workflow built on top of [NVIDIA NeMo Agent Toolkit (NAT)](https://github.com/NVIDIA/NeMo-Agent-Toolkit) and LangGraph. It orchestrates planner, constructor, inspector, router, rot, and DeerFlow-backed components behind a lightweight local server and HTML demo.

> This repository contains the Renkai project code only. NAT itself is expected to be installed as a dependency.

## Architecture

| Module | Responsibility |
|---|---|
| `agents/planner/` | Planner workflow package |
| `agents/router/` | Router workflow package |
| `agents/constructor/` | Constructor workflow package |
| `agents/inspector/` | Inspector workflow package |
| `agents/rot/` | Top-level orchestration workflow package |
| `backend/deerflow/` | Checked-in DeerFlow agent package (`deerflow_agent`) |
| `backend/gateway/` | Reserved gateway location; no gateway source is present in this workspace snapshot |
| `frontend/renkai_demo.html` | Static demo frontend |
| `runtime/` | Generated plans, outputs, logs, cache, and other run artifacts |
| `server.py` | Local HTTP server for the demo and NAT pipeline control |

## Prerequisites

- Python 3.11, 3.12, or 3.13
- [uv](https://docs.astral.sh/uv/)
- NVIDIA and/or OpenAI API credentials depending on your configured models

## Installation

```bash
uv venv --python 3.12 --seed .venv
source .venv/bin/activate
uv pip install -r requirements.txt
nat --version
```

Create a local `.env` file from `.env.example` and set `NVIDIA_API_KEY`. The
`.env` file is gitignored and must never be committed.

```bash
cp .env.example .env
# Edit .env and replace `your_key_here` with your NVIDIA API key.
```

## Running

The checked-in server entrypoint now assumes the repository root is the working directory:

```bash
source .venv/bin/activate
python server.py
```

To run the ROT workflow directly, use the included launcher. It loads the
gitignored `.env` file before it starts NAT:

```bash
./scripts/run_rot.sh "what is machine learning?"
```

The DeerFlow package in this snapshot lives under `backend/deerflow/`. The gateway directory has been created at `backend/gateway/`, but no gateway application source is present in this workspace, so any gateway-specific startup command still requires that missing source to be restored.

Open `frontend/renkai_demo.html` in a browser, or browse to `http://localhost:8000` while `server.py` is running.

## Project Structure

```text
renkai/
|-- agents/
|   |-- constructor/
|   |-- inspector/
|   |-- planner/
|   |-- rot/
|   `-- router/
|-- backend/
|   |-- deerflow/
|   `-- gateway/
|-- config/
|-- frontend/
|   `-- renkai_demo.html
|-- models/
|-- prompts/
|-- runtime/
|   |-- cache/
|   |-- generated/
|   |-- logs/
|   `-- outputs/
|-- services/
|-- tests/
|-- utils/
|-- .env.example
|-- .gitignore
|-- README.md
|-- requirements.txt
`-- server.py
```
# renk_ai
