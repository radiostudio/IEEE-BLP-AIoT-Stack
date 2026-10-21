#!/usr/bin/env bash
# Runs any gateway command through the environment setup.sh built, with no
# manual "activate" step. Example: bash gateway.sh simulate
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv-gateway/bin/python3"

if [ ! -x "$VENV_PY" ]; then
    echo "The gateway isn't set up yet. Run this first:"
    echo "  bash setup.sh"
    exit 1
fi

exec "$VENV_PY" -m gateway "$@"
