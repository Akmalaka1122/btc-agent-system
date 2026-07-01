"""
tools.py — Tool registry for ReAct-style agent tool-calling.

Each tool is an async function that takes keyword args and returns a dict/string.
Tools are registered with a name, description, and parameter schema.
Agents can call tools mid-reasoning to verify data before final decisions.

Pattern: Meridian-style tool layer — separated from reasoning, ensures
agent doesn't "hallucinate" data results.
"""
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("tools")


class Tool:
    """A callable tool that an agent can invoke during reasoning."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: Callable,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema for parameters
        self.func = func

    def to_openai_schema(self) -> dict:
        """Export as OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, **kwargs) -> str:
        """Execute the tool and return result as string."""
        try:
            result = await self.func(**kwargs)
            if isinstance(result, dict):
                import json
                return json.dumps(result, indent=2, default=str)
            return str(result)
        except Exception as e:
            logger.warning(f"Tool {self.name} failed: {e}")
            return f"ERROR: {e}"


class ToolRegistry:
    """Registry of tools available to agents."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: Callable,
    ) -> Tool:
        tool = Tool(name, description, parameters, func)
        self._tools[name] = tool
        return tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def to_openai_tools(self) -> list[dict]:
        """Export all tools as OpenAI function-calling schema list."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def to_text_description(self) -> str:
        """Export tools as text prompt (for providers without native tool-calling)."""
        lines = ["## Available Tools\n"]
        lines.append("You can call these tools to verify data before making your decision.")
        lines.append('To call a tool, output a JSON block like:\n```tool_call\n{"name": "tool_name", "args": {"param": "value"}}\n```\n')
        lines.append("After seeing the result, continue reasoning or output your final answer.\n")
        for t in self._tools.values():
            params_desc = []
            props = t.parameters.get("properties", {})
            required = t.parameters.get("required", [])
            for pname, pinfo in props.items():
                req = " (required)" if pname in required else " (optional)"
                params_desc.append(f"    - {pname}: {pinfo.get('description', pinfo.get('type', 'any'))}{req}")
            lines.append(f"### `{t.name}`")
            lines.append(f"{t.description}")
            if params_desc:
                lines.append("Parameters:")
                lines.extend(params_desc)
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Default tools for BTC trading
# ---------------------------------------------------------------------------

def create_btc_tools(binance_client=None, polymarket_client=None) -> ToolRegistry:
    """Create a ToolRegistry with standard BTC trading tools."""
    registry = ToolRegistry()

    # --- get_current_price ---
    async def _get_price(symbol: str = "BTCUSDT") -> dict:
        if not binance_client:
            return {"error": "Binance client not available"}
        price = await binance_client.get_price(symbol)
        return {"symbol": symbol, "price": price}

    registry.register(
        name="get_current_price",
        description="Get the current BTC price from Binance. Use to verify price before final decision.",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair (default: BTCUSDT)",
                    "default": "BTCUSDT",
                },
            },
            "required": [],
        },
        func=_get_price,
    )

    # --- get_orderbook ---
    async def _get_orderbook(symbol: str = "BTCUSDT", limit: int = 10) -> dict:
        if not binance_client:
            return {"error": "Binance client not available"}
        book = await binance_client.get_orderbook_snapshot(symbol=symbol, limit=limit)
        return {
            "best_bid": book["best_bid"],
            "best_ask": book["best_ask"],
            "spread": book["spread"],
            "bid_volume": round(book["bid_volume"], 4),
            "ask_volume": round(book["ask_volume"], 4),
            "bid_ask_imbalance": round(book["bid_ask_imbalance"], 4),
            "interpretation": (
                "bid-heavy (bullish pressure)" if book["bid_ask_imbalance"] > 0.55
                else "ask-heavy (bearish pressure)" if book["bid_ask_imbalance"] < 0.45
                else "balanced"
            ),
        }

    registry.register(
        name="get_orderbook",
        description="Get BTC orderbook depth snapshot. Shows bid/ask imbalance — useful to verify buy/sell pressure before trade.",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair", "default": "BTCUSDT"},
                "limit": {"type": "integer", "description": "Depth levels (5, 10, 20)", "default": 10},
            },
            "required": [],
        },
        func=_get_orderbook,
    )

    # --- get_funding_rate ---
    async def _get_funding(symbol: str = "BTCUSDT") -> dict:
        if not binance_client:
            return {"error": "Binance client not available"}
        data = await binance_client.get_funding_rate(symbol)
        fr = data["funding_rate"]
        return {
            "funding_rate": f"{fr:+.6f}",
            "funding_rate_pct": f"{fr * 100:+.4f}%",
            "mark_price": data["mark_price"],
            "interpretation": (
                "longs pay shorts — bullish crowding" if fr > 0.01
                else "shorts pay longs — bearish crowding" if fr < -0.01
                else "neutral"
            ),
        }

    registry.register(
        name="get_funding_rate",
        description="Get BTC futures funding rate. Positive = longs pay shorts (bullish crowding), negative = opposite.",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair", "default": "BTCUSDT"},
            },
            "required": [],
        },
        func=_get_funding,
    )

    # --- get_polymarket_odds ---
    async def _get_odds(token_id: str = "") -> dict:
        import os
        if not polymarket_client:
            return {"error": "Polymarket client not available"}
        tid = token_id or os.getenv("POLYMARKET_TOKEN_ID", "")
        if not tid:
            return {"error": "No token_id provided and POLYMARKET_TOKEN_ID not set"}
        return await polymarket_client.get_market_odds(tid)

    registry.register(
        name="get_polymarket_odds",
        description="Get current Polymarket implied odds for the BTC 5m market. Use to check EV before trading.",
        parameters={
            "type": "object",
            "properties": {
                "token_id": {
                    "type": "string",
                    "description": "Polymarket token ID (leave empty to use POLYMARKET_TOKEN_ID env var)",
                    "default": "",
                },
            },
            "required": [],
        },
        func=_get_odds,
    )

    # --- get_recent_candles ---
    async def _get_candles(symbol: str = "BTCUSDT", interval: str = "5m", limit: int = 10) -> dict:
        if not binance_client:
            return {"error": "Binance client not available"}
        candles = await binance_client.get_ohlcv(symbol=symbol, interval=interval, limit=limit)
        # Return last 5 in compact form
        recent = []
        for c in candles[-5:]:
            recent.append({
                "time": c["open_time"].strftime("%H:%M"),
                "O": c["open"],
                "H": c["high"],
                "L": c["low"],
                "C": c["close"],
                "V": round(c["volume"], 2),
            })
        # Compute simple trend
        if len(candles) >= 2:
            change = (candles[-1]["close"] - candles[-2]["close"]) / candles[-2]["close"] * 100
        else:
            change = 0
        return {
            "candles": recent,
            "last_price": candles[-1]["close"],
            "last_2_candle_change_pct": round(change, 4),
        }

    registry.register(
        name="get_recent_candles",
        description="Get recent BTC candles. Shows last 5 candles with OHLCV. Use to verify trend direction.",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Trading pair", "default": "BTCUSDT"},
                "interval": {"type": "string", "description": "Candle interval (1m, 5m, 15m, 1h)", "default": "5m"},
                "limit": {"type": "integer", "description": "Number of candles", "default": 10},
            },
            "required": [],
        },
        func=_get_candles,
    )

    return registry
