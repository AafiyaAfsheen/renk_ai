#!/usr/bin/env bash
# Run the ROT workflow with environment variables from the repository's .env.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
CONFIG_FILE="$ROOT_DIR/agents/rot/src/rot/configs/config.yml"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing $ENV_FILE. Copy .env.example to .env and set NVIDIA_API_KEY." >&2
    exit 1
fi

# Export entries from the local, gitignored environment file to NAT.
set -a
source "$ENV_FILE"
set +a

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
    echo "NVIDIA_API_KEY is not set in $ENV_FILE." >&2
    exit 1
fi

NAT_BIN="$ROOT_DIR/.venv/bin/nat"

if [[ ! -x "$NAT_BIN" ]]; then
    echo "Missing RENKAI virtual environment at $ROOT_DIR/.venv. Install workspace dependencies first." >&2
    exit 1
fi

exec "$NAT_BIN" run --config_file "$CONFIG_FILE" --input "$*"
