"""FIRE Simulator MCP server entry point.

Run via:
    python -m mcp_server.server

Configured in ~/.claude.json under mcpServers.fire-simulator. The Claude Code
client spawns this as a stdio subprocess.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make `simulator.*` and `deps` importable when invoked as `python -m mcp_server.server`
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Logging — stderr only (stdio transport uses stdout for protocol)
logging.basicConfig(
    level=logging.WARNING,
    stream=sys.stderr,
    format="[fire-mcp] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


from mcp.server.fastmcp import FastMCP  # noqa: E402

from mcp_server.tools import (  # noqa: E402
    fire_simulate,
    fire_sweep_withdrawal,
    fire_swr_for_target,
    fire_guardrail,
    fire_list_countries,
)

mcp = FastMCP("fire-simulator")

mcp.tool()(fire_simulate)
mcp.tool()(fire_sweep_withdrawal)
mcp.tool()(fire_swr_for_target)
mcp.tool()(fire_guardrail)
mcp.tool()(fire_list_countries)


def _warmup() -> None:
    """Preload JST returns + country DFs so first tool call is fast."""
    try:
        from deps import get_returns_df, get_country_dfs_cached
        get_returns_df("jst")
        get_country_dfs_cached(1900, "jst")
        logger.info("warmup ok")
    except Exception as e:
        logger.warning("warmup failed: %s", e)


if __name__ == "__main__":
    _warmup()
    mcp.run()
