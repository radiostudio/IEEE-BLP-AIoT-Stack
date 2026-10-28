"""Shared context handed to every MCP tool.

Tools are plain functions over this context so they can be exercised directly
by tests and by the agents' orchestrator without an MCP transport in between.
server.py wraps the same functions for Claude and other MCP clients.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core import RULES_DIR, load_config
from ..decoder.registry import CardRegistry
from ..store import open_store
from ..store.db import Store


@dataclass
class GatewayContext:
    store: Store  # or store.influx.InfluxStore: same methods
    registry: CardRegistry
    rules_dir: Path = RULES_DIR
    capability_token_file: Path = RULES_DIR.parent / ".capability_token"

    @classmethod
    def from_config(cls, config: dict | None = None) -> "GatewayContext":
        cfg = config or load_config()
        return cls(store=open_store(cfg), registry=CardRegistry())
