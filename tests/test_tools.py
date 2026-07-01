"""test_tools.py — tests for tool registry and ReAct tool-calling."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.tools import Tool, ToolRegistry, create_btc_tools


class TestToolRegistry:
    def test_register_and_get(self):
        """Tools can be registered and retrieved by name."""
        registry = ToolRegistry()
        tool = registry.register(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            func=AsyncMock(return_value={"result": 42}),
        )
        assert registry.get("test_tool") is tool
        assert registry.get("nonexistent") is None

    def test_list_tools(self):
        """list_tools returns all registered tools."""
        registry = ToolRegistry()
        registry.register("a", "desc a", {}, AsyncMock())
        registry.register("b", "desc b", {}, AsyncMock())
        assert len(registry.list_tools()) == 2

    def test_to_openai_tools(self):
        """Export as OpenAI function-calling schema."""
        registry = ToolRegistry()
        registry.register(
            name="get_price",
            description="Get BTC price",
            parameters={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
            func=AsyncMock(),
        )
        tools = registry.to_openai_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "get_price"

    def test_to_text_description(self):
        """Export as text description for providers without native tool-calling."""
        registry = ToolRegistry()
        registry.register(
            name="get_price",
            description="Get BTC price",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Trading pair"},
                },
                "required": ["symbol"],
            },
            func=AsyncMock(),
        )
        text = registry.to_text_description()
        assert "get_price" in text
        assert "Get BTC price" in text
        assert "```tool_call" in text  # instructions for how to call


class TestToolExecution:
    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Tool execution returns stringified result."""
        async def my_func(x: int = 1):
            return {"value": x * 2}

        tool = Tool("double", "Double a number", {"type": "object", "properties": {}}, my_func)
        result = await tool.execute(x=5)
        assert "10" in result

    @pytest.mark.asyncio
    async def test_execute_error(self):
        """Tool execution catches errors and returns error string."""
        async def bad_func():
            raise ValueError("boom")

        tool = Tool("bad", "Bad tool", {"type": "object", "properties": {}}, bad_func)
        result = await tool.execute()
        assert "ERROR" in result
        assert "boom" in result


class TestCreateBtcTools:
    def test_creates_all_tools(self):
        """create_btc_tools registers all standard tools."""
        registry = create_btc_tools()
        tool_names = [t.name for t in registry.list_tools()]
        assert "get_current_price" in tool_names
        assert "get_orderbook" in tool_names
        assert "get_funding_rate" in tool_names
        assert "get_polymarket_odds" in tool_names
        assert "get_recent_candles" in tool_names
