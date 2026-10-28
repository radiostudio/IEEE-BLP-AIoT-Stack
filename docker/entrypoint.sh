#!/bin/sh
# Container entrypoint: seeds the shipped edge rules into the mounted data
# folder on first start, then runs a gateway command (default: run).
set -e

if [ -n "$GATEWAY_RULES_DIR" ] && [ ! -d "$GATEWAY_RULES_DIR" ]; then
    # first start only: never overwrite rules a human has approved since
    mkdir -p "$GATEWAY_RULES_DIR"
    cp /app/gateway/rules/rules.d/*.json "$GATEWAY_RULES_DIR"/ 2>/dev/null || true
    echo "[entrypoint] seeded $GATEWAY_RULES_DIR with the shipped rules"
fi

exec python -m gateway "$@"
