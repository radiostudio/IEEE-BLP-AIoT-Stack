"""FastMCP server: the gateway's product surface.

Runs over stdio for a local Claude Desktop / Claude Code connection; the same
process works unchanged on Raspberry Pi and Uno Q. Requires the `mcp` package
(pip install mcp); everything else in the gateway runs without it.

Claude Desktop config example (Windows dev):
{
  "mcpServers": {
    "aiot-gateway": {
      "command": "python",
      "args": ["-m", "gateway", "mcp"],
      "cwd": "D:/downloads/IEEE_BLP/vibecoding/revised_course/ai_first_course"
    }
  }
}
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core import PACKAGE_DIR
from .context import GatewayContext
from .tools import annotate as t_annotate
from .tools import capture_experiment as t_capture
from .tools import deploy_rule as t_deploy
from .tools import describe_sensor as t_describe
from .tools import list_sensors as t_list
from .tools import query_timeseries as t_query
from .tools import read_latest as t_read
from .tools import validate_reading as t_validate

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


def build_server(ctx: GatewayContext | None = None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "the 'mcp' package is not installed. Run: pip install mcp") from exc

    ctx = ctx or GatewayContext.from_config()
    mcp = FastMCP(
        "aiot-gateway",
        host="0.0.0.0",
        port=8000,
        instructions=(
            "RadioStudio AIoT and Climate Change kit gateway. Sensors are "
            "described by machine-readable cards: call describe_sensor before "
            "interpreting any reading, and validate_reading before trusting "
            "one. Ask the user for physical context and record it with "
            "annotate. Rules you deploy require human approval before they run."
        ),
    )

    @mcp.tool()
    def list_sensors() -> list[dict]:
        """Live sensor inventory with last-seen age, status, delivery ratio."""
        return t_list.list_sensors(ctx)

    @mcp.tool()
    def describe_sensor(sensor: str) -> dict:
        """Full sensor card (ranges, accuracy, payload layout, failure modes)
        for a uid like '1:6' or a bare sensor_type_id like '6'."""
        return t_describe.describe_sensor(ctx, sensor)

    @mcp.tool()
    def read_latest(sensor_uid: str) -> dict:
        """Most recent value per measurand for one sensor uid."""
        return t_read.read_latest(ctx, sensor_uid)

    @mcp.tool()
    def query_timeseries(sensor_uid: str, field: str, start: float, end: float,
                         agg: str | None = None, bucket_s: int = 60) -> dict:
        """Series between epoch seconds start/end. agg: mean|min|max buckets
        of bucket_s, or omit for raw points (tick-reconciled timestamps)."""
        return t_query.query_timeseries(ctx, sensor_uid, field, start, end,
                                        agg, bucket_s)

    @mcp.tool()
    def capture_experiment(name: str, sensors: list[str],
                           duration_s: float | None = None,
                           sampling: str | None = None) -> dict:
        """Open a named multi-sensor capture window; returns a dataset handle."""
        return t_capture.capture_experiment(ctx, name, sensors, duration_s, sampling)

    @mcp.tool()
    def end_experiment(experiment_id: int) -> dict:
        """Close a capture window opened by capture_experiment."""
        return t_capture.end_experiment(ctx, experiment_id)

    @mcp.tool()
    def annotate(note: str, sensor_uid: str | None = None,
                 author: str | None = None) -> dict:
        """Deployment journal: record physical context the sensors cannot see
        (mounting, moved sensors, 'window opened', acceptance test results)."""
        return t_annotate.annotate(ctx, note, sensor_uid, author)

    @mcp.tool()
    def list_annotations(since: float = 0.0) -> list[dict]:
        """Read the deployment journal, optionally since an epoch timestamp."""
        return t_annotate.list_annotations(ctx, since)

    @mcp.tool()
    def validate_reading(sensor_uid: str, field: str,
                         value: float | None = None) -> dict:
        """Verdict (plausible/implausible/stale/invalid) with reasoning, from
        the card's plausibility bounds, rate limits, status bits, staleness."""
        return t_validate.validate_reading(ctx, sensor_uid, field, value)

    @mcp.tool()
    def deploy_rule(spec: dict, capability_token: str) -> dict:
        """Submit a deterministic edge rule (JSON spec). Requires the gateway's
        capability token and lands as pending until a human approves it."""
        return t_deploy.deploy_rule(ctx, spec, capability_token)

    # Resources: every sensor card, plus any datasheets dropped in resources/.
    for card in ctx.registry.all_cards():
        uri = f"card://{card.sensor_type_id}"
        doc = card.doc

        def _make(doc=doc):
            def _read() -> str:
                return json.dumps(doc, indent=2)
            return _read

        mcp.resource(uri, name=f"sensor-card-{card.sensor_type_id}",
                     description=f"Sensor card: {card.part}")(_make())

    if PROMPTS_DIR.exists():
        for prompt_file in sorted(PROMPTS_DIR.glob("*.md")):
            text = prompt_file.read_text(encoding="utf-8")

            def _make_prompt(text=text):
                def _prompt() -> str:
                    return text
                return _prompt

            mcp.prompt(name=prompt_file.stem)(_make_prompt())

    return mcp


def main() -> None:
    build_server().run()  # stdio transport


if __name__ == "__main__":
    main()
