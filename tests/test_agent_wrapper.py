"""test_agent_wrapper.py — Agent LLM wrapper tests with mocked API."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.agent import Agent, AgentTimeoutError, AgentAPIError, AgentVerificationError
from core.schemas import TraderAction


class TestAgent:
    def _make_agent(self, output_schema=None):
        """Create agent with minimal soul file for testing."""
        agent = Agent.__new__(Agent)
        agent.name = "TestAgent"
        agent.soul_path = None
        agent.technical_prompt = ""
        agent.output_schema = output_schema
        agent.timeout_s = 10.0
        agent._soul_text = "You are a test agent."
        agent._client = None
        return agent

    def test_system_prompt_basic(self):
        agent = self._make_agent()
        prompt = agent._system_prompt()
        assert "test agent" in prompt.lower()

    def test_system_prompt_with_schema(self):
        from core.schemas import MarketReport
        agent = self._make_agent(output_schema=MarketReport)
        prompt = agent._system_prompt()
        assert "JSON" in prompt
        assert "net_market_bias" in prompt

    @pytest.mark.asyncio
    async def test_openai_call_success(self):
        """Mock successful OpenAI-compatible API call."""
        agent = self._make_agent()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "ok"}'

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("core.agent.AsyncOpenAI", return_value=mock_client), \
             patch("core.agent._get_config", return_value={
                 "provider": "openai", "sdk": "openai",
                 "base_url": "http://test", "api_key": "test-key",
                 "model": "test-model", "max_tokens": 100, "temperature": 0.3,
             }):
            result = await agent.run("test input")
            assert result["raw"] == '{"result": "ok"}'
            assert result["parsed"] is None  # no schema

    @pytest.mark.asyncio
    async def test_empty_choices_raises(self):
        """Empty response.choices should raise AgentVerificationError."""
        agent = self._make_agent()

        mock_response = MagicMock()
        mock_response.choices = []

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("core.agent.AsyncOpenAI", return_value=mock_client), \
             patch("core.agent._get_config", return_value={
                 "provider": "openai", "sdk": "openai",
                 "base_url": "http://test", "api_key": "test-key",
                 "model": "test-model", "max_tokens": 100, "temperature": 0.3,
             }):
            with pytest.raises(AgentVerificationError, match="empty response"):
                await agent.run("test")

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Timeout exception should raise AgentTimeoutError."""
        agent = self._make_agent()

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Request timed out after 10s")
        )

        with patch("core.agent.AsyncOpenAI", return_value=mock_client), \
             patch("core.agent._get_config", return_value={
                 "provider": "openai", "sdk": "openai",
                 "base_url": "http://test", "api_key": "test-key",
                 "model": "test-model", "max_tokens": 100, "temperature": 0.3,
             }):
            with pytest.raises(AgentTimeoutError, match="timed out"):
                await agent.run("test")

    @pytest.mark.asyncio
    async def test_auth_error(self):
        """401 error should raise AgentAPIError."""
        agent = self._make_agent()

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("401 Unauthorized")
        )

        with patch("core.agent.AsyncOpenAI", return_value=mock_client), \
             patch("core.agent._get_config", return_value={
                 "provider": "openai", "sdk": "openai",
                 "base_url": "http://test", "api_key": "test-key",
                 "model": "test-model", "max_tokens": 100, "temperature": 0.3,
             }):
            with pytest.raises(AgentAPIError, match="auth failed"):
                await agent.run("test")

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """429 error should raise AgentAPIError."""
        agent = self._make_agent()

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("429 Too Many Requests")
        )

        with patch("core.agent.AsyncOpenAI", return_value=mock_client), \
             patch("core.agent._get_config", return_value={
                 "provider": "openai", "sdk": "openai",
                 "base_url": "http://test", "api_key": "test-key",
                 "model": "test-model", "max_tokens": 100, "temperature": 0.3,
             }):
            with pytest.raises(AgentAPIError, match="rate limited"):
                await agent.run("test")

    @pytest.mark.asyncio
    async def test_schema_parse_success(self):
        """Valid JSON with schema should parse successfully."""
        from core.schemas import TraderProposal, TraderAction
        agent = self._make_agent(output_schema=TraderProposal)

        valid_json = (
            '{"action": "UP", "confidence": 7, "reasoning": "test", '
            '"entry_price": 100000.0, "expected_move_pct": 0.5, '
            '"position_size_usd": 500.0, "max_loss_usd": 100.0, '
            '"market_odds": 0.55, "expected_value": 0.12}'
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_json

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("core.agent.AsyncOpenAI", return_value=mock_client), \
             patch("core.agent._get_config", return_value={
                 "provider": "openai", "sdk": "openai",
                 "base_url": "http://test", "api_key": "test-key",
                 "model": "test-model", "max_tokens": 100, "temperature": 0.3,
             }):
            result = await agent.run("test")
            assert result["parsed"] is not None
            assert result["parsed"].action == TraderAction.UP

    @pytest.mark.asyncio
    async def test_markdown_fence_stripping(self):
        """LLM wrapped JSON in ```json ... ``` — should strip and parse."""
        from core.schemas import TraderProposal
        agent = self._make_agent(output_schema=TraderProposal)

        valid_json = (
            '```json\n'
            '{"action": "SKIP", "confidence": 3, "reasoning": "test", '
            '"entry_price": 100000.0, "expected_move_pct": 0, '
            '"position_size_usd": 0, "max_loss_usd": 0, '
            '"market_odds": 0.5, "expected_value": 0}\n'
            '```'
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_json

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("core.agent.AsyncOpenAI", return_value=mock_client), \
             patch("core.agent._get_config", return_value={
                 "provider": "openai", "sdk": "openai",
                 "base_url": "http://test", "api_key": "test-key",
                 "model": "test-model", "max_tokens": 100, "temperature": 0.3,
             }):
            result = await agent.run("test")
            assert result["parsed"] is not None
            assert result["parsed"].action == TraderAction.SKIP
