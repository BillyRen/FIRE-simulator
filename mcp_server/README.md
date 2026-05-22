# FIRE Simulator MCP Server

Stdio MCP server exposing 5 retirement simulation tools to Claude Code. Wraps `simulator/*` pure-Python computation; no HTTP backend required.

## Installation

```bash
/Users/billy.ren/miniforge3/bin/pip install 'mcp[cli]'
```

(Backend deps — numpy / pandas / scipy / fastapi — are reused; ensure they are installed in the same Python env.)

## Configuration

Add to `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "fire-simulator": {
      "command": "/Users/billy.ren/miniforge3/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/Users/billy.ren/Projects/FIRE_simulator",
      "env": {
        "PYTHONPATH": "/Users/billy.ren/Projects/FIRE_simulator"
      }
    }
  }
}
```

Restart Claude Code; the 5 tools become available globally in any repo.

## Tools

| Tool | Purpose | Typical latency (2000 sims) |
|------|---------|---|
| `fire_simulate` | Single Monte Carlo run -> success rate, P10/P50/P90 trajectory | < 1s |
| `fire_sweep_withdrawal` | Sweep withdrawal rates 0..rate_max, find SWR at 75/80/85/90/95/100% targets | 1-3s |
| `fire_swr_for_target` | One-shot: SWR for a given target_success | 1-3s |
| `fire_guardrail` | Guyton-Klinger guardrail vs fixed baseline, effFR comparison | 2-5s |
| `fire_list_countries` | List valid ISO codes + year ranges | instant |

All tools have sensible defaults (1M portfolio, 40K/yr, USA, 65 years, fixed strategy, 2000 sims, JST data). Claude can call them with zero args for the canonical 4% rule scenario.

## Common usage patterns

```
"What's the success rate for $1.5M, 60-year retirement, ALL countries pool, 3.5%?"
-> fire_simulate(initial_portfolio=1_500_000, annual_withdrawal=52_500, country="ALL", retirement_years=60)

"What SWR gives 90% success?"
-> fire_swr_for_target(target_success=0.90)

"Compare 3.3% fixed vs guardrail for default scenario"
-> fire_guardrail()  # baseline_rate defaults to 0.033

"What countries can I query?"
-> fire_list_countries()
```

## Gotchas

- ISO codes are 3-letter: `CHN` not `CN`, `GBR` not `UK`, `JPN` not `JP`. Use `fire_list_countries` to discover.
- `country="ALL"` enables GDP-sqrt-weighted pooled bootstrap (recommended for globally diversified investors). With `data_source="fire_dataset"`, `"ALL"` silently coerces to `"USA"`.
- v1 does NOT expose cash flows (CFs). Use the web UI at fire.rens.ai for CF scenarios.
- `fire_guardrail` num_simulations capped at 5000 (memory); others at 20000.
- `leverage > 1.0` applies borrowing at 2% real spread.

## Files

- `server.py` — entry point, `python -m mcp_server.server`
- `tools.py` — 5 tool implementations
- `helpers.py` — shared: data resolution, allocation builder, error mapping
- `__init__.py` — package marker

## Validation

In-process smoke test (bypasses MCP transport):

```python
import sys
sys.path.insert(0, "/Users/billy.ren/Projects/FIRE_simulator")
sys.path.insert(0, "/Users/billy.ren/Projects/FIRE_simulator/backend")
from mcp_server.tools import fire_simulate
print(fire_simulate(num_simulations=500, seed=42)["success_rate"])
```

Protocol smoke test (boots server, sends initialize + tools/list):

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' | \
  /Users/billy.ren/miniforge3/bin/python -m mcp_server.server
```

## Maintenance

Dependencies are shared with `backend/`. When upgrading numpy / pandas / scipy in `backend/requirements.txt`, also run:

```bash
/Users/billy.ren/miniforge3/bin/pip install -U -r backend/requirements.txt
```

## Out of scope (v1)

- Cash flows (probability groups, inflation adjustment, growth rates)
- Buy vs rent comparison
- Accumulation phase calculator
- Sensitivity / allocation 2D sweeps
- Streaming progress notifications

These remain web-UI-only features at fire.rens.ai.
