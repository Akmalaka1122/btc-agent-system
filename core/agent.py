"""
agent.py — multi-provider LLM wrapper.

Supports:
  - OpenAI-compatible providers: OpenRouter, DeepSeek, Xiaomi, OpenAI, Xpiki, Conduit
  - Anthropic native SDK: claude-sonnet-4, claude-opus-4

Provider is selected via LLM_PROVIDER env var:
  openrouter | deepseek | xiaomi | openai | anthropic | openai-compatible
"""
import os
import json
import logging
import re
from pathlib import Path
from typing import Optional, Type
from pydantic import BaseModel
from openai import AsyncOpenAI

logger = logging.getLogger("agent")

SOULS_DIR = Path(__file__).parent.parent / "souls"


def _extract_json_object(text: str) -> str:
    """
    Extract the first complete JSON object from text.
    Handles trailing text, prose before/after the JSON block.
    Falls back to brace-matching if prefix/postfix noise exists.
    """
    text = text.strip()
    # Find first '{'
    start = text.find("{")
    if start == -1:
        return text  # no object found, return as-is (will fail validation)

    # Brace-match to find closing '}'
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    # Braces didn't balance — return from first '{' to end (will fail validation)
    return text[start:]


# ---------------------------------------------------------------------------
# Provider registry — URLs, default models, and SDK selection
# ---------------------------------------------------------------------------
PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-sonnet-4",
        "sdk": "openai",
    },
    "xiaomi": {
        "base_url": "https://api.xiaomimimo.com/v1",
        "default_model": "mimo-v2.5-pro",
        "sdk": "openai",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "sdk": "openai",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "sdk": "openai",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "sdk": "anthropic",
    },
    "zyloo": {
        "base_url": "https://api.zyloo.io/v1",
        "default_model": "claude-opus-4-7",
        "sdk": "openai",
    },
    "openai-compatible": {
        # Generic fallback for Xpiki, Conduit, etc.
        "base_url": None,  # must be set via LLM_BASE_URL
        "default_model": None,  # must be set via LLM_MODEL
        "sdk": "openai",
    },
}


def _get_config() -> dict:
    """Lazy config — reads .env every call, so values are always current.

    Provider resolution:
      - If LLM_PROVIDER matches a registered provider (not 'openai-compatible'),
        the registry provides base_url and model. API key is read from
        <PROVIDER>_API_KEY env var, falling back to LLM_API_KEY.
      - If LLM_PROVIDER is 'openai-compatible' or unknown, LLM_BASE_URL,
        LLM_API_KEY, and LLM_MODEL env vars are used directly.
    """
    provider_name = os.getenv("LLM_PROVIDER", "xiaomi").lower()
    provider = PROVIDERS.get(provider_name)

    if provider and provider_name != "openai-compatible":
        # Named provider — use registry values, provider-specific API key
        base_url = provider["base_url"]
        model = os.getenv("LLM_MODEL") or provider["default_model"]
        api_key_env = f"{provider_name.upper()}_API_KEY"
        api_key = os.getenv(api_key_env) or os.getenv("LLM_API_KEY", "")
    else:
        # Generic openai-compatible — all from env vars
        provider = PROVIDERS.get("openai-compatible", {})
        base_url = os.getenv("LLM_BASE_URL", "")
        model = os.getenv("LLM_MODEL", "")
        api_key = os.getenv("LLM_API_KEY", "")

    return {
        "provider": provider_name,
        "sdk": provider.get("sdk", "openai"),
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "2000")),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.3")),
    }


class AgentTimeoutError(Exception):
    pass


class AgentAPIError(Exception):
    """Non-timeout API errors (auth, rate limit, server error)."""
    pass


class AgentVerificationError(Exception):
    pass


class Agent:
    def __init__(
        self,
        name: str,
        soul_file: str,
        technical_prompt: str = "",
        output_schema: Optional[Type[BaseModel]] = None,
        timeout_s: float = 30.0,
        tools=None,
    ):
        self.name = name
        self.soul_path = SOULS_DIR / soul_file
        self.technical_prompt = technical_prompt
        self.output_schema = output_schema
        self.timeout_s = timeout_s
        self._soul_text = self._load_soul()
        self._client = None  # lazy init per-run to pick up latest config
        self.tools = tools  # ToolRegistry (optional)

    def _load_soul(self) -> str:
        if not self.soul_path.exists():
            raise FileNotFoundError(f"Soul file not found: {self.soul_path}")
        return self.soul_path.read_text(encoding="utf-8")

    def _system_prompt(self) -> str:
        parts = [self._soul_text]
        if self.technical_prompt:
            parts.append("\n---\n## Technical Spec & Output Schema\n" + self.technical_prompt)
        if self.output_schema:
            parts.append(
                "\n---\nIMPORTANT: Respond ONLY with valid JSON matching this schema, "
                "no markdown, no preamble:\n"
                + json.dumps(self.output_schema.model_json_schema(), indent=2)
            )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # OpenAI-compatible call (OpenRouter, DeepSeek, Xiaomi, OpenAI, etc.)
    # ------------------------------------------------------------------
    async def _call_openai(self, cfg: dict, system: str, user: str) -> str:
        client = AsyncOpenAI(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            timeout=self.timeout_s,
        )
        response = await client.chat.completions.create(
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if not response.choices:
            raise AgentVerificationError(f"{self.name} returned empty response (no choices)")
        msg = response.choices[0].message
        content = msg.content or ""

        # Handle reasoning models (MiMo, DeepSeek R1, etc.)
        # These models put the actual answer in `content` and reasoning in
        # `reasoning_content`. If content is empty, fall back to reasoning_content.
        if not content and hasattr(msg, "reasoning_content"):
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning:
                logger.info(f"{self.name}: content empty, using reasoning_content ({len(reasoning)} chars)")
                content = reasoning

        if not content:
            raise AgentVerificationError(f"{self.name} returned empty content")

        return content

    # ------------------------------------------------------------------
    # Anthropic native SDK call
    # ------------------------------------------------------------------
    async def _call_anthropic(self, cfg: dict, system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError:
            raise AgentAPIError(
                "anthropic SDK not installed. Run: pip install anthropic"
            )

        client = anthropic.AsyncAnthropic(
            api_key=cfg["api_key"],
            timeout=self.timeout_s,
        )
        response = await client.messages.create(
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if not response.content:
            raise AgentVerificationError(f"{self.name} returned empty response (no content)")
        # Anthropic returns list of content blocks; extract text
        text_parts = [block.text for block in response.content if hasattr(block, "text")]
        return "\n".join(text_parts) or ""

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    async def run(self, user_message: str) -> dict:
        """Returns {'raw': str, 'parsed': BaseModel | None}"""
        cfg = _get_config()
        system = self._system_prompt()

        try:
            if cfg["sdk"] == "anthropic":
                raw_text = await self._call_anthropic(cfg, system, user_message)
            else:
                raw_text = await self._call_openai(cfg, system, user_message)
        except AgentVerificationError:
            raise  # let verification errors pass through
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg or "timed out" in err_msg:
                raise AgentTimeoutError(f"{self.name} timed out after {self.timeout_s}s: {e}")
            if "auth" in err_msg or "401" in err_msg or "403" in err_msg:
                raise AgentAPIError(f"{self.name} auth failed: {e}")
            if "rate" in err_msg or "429" in err_msg:
                raise AgentAPIError(f"{self.name} rate limited: {e}")
            raise AgentAPIError(f"{self.name} API error: {e}")

        parsed = None
        if self.output_schema:
            try:
                clean = raw_text.strip()
                # Strip markdown code fences (handles ```json, ```JSON, etc.)
                if clean.startswith("```"):
                    first_line_end = clean.index("\n") if "\n" in clean else len(clean)
                    clean = clean[first_line_end + 1:] if first_line_end < len(clean) else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
                # Extract JSON object robustly (handles trailing text/prose)
                clean = _extract_json_object(clean)
                parsed = self.output_schema.model_validate_json(clean)
            except Exception as e:
                logger.warning(f"{self.name} schema validation failed: {e}")
                raise AgentVerificationError(
                    f"{self.name} output failed schema validation: {e}"
                )

        return {"raw": raw_text, "parsed": parsed}

    # ------------------------------------------------------------------
    # ReAct loop — Reason → Act → Observe → repeat
    # ------------------------------------------------------------------
    async def run_react(self, user_message: str, max_iterations: int = 3) -> dict:
        """
        ReAct-style execution: agent reasons, calls tools if needed,
        observes results, and loops until final answer.

        For providers without native tool-calling, uses text-based
        tool_call JSON blocks in the LLM output.

        Returns same format as run(): {'raw': str, 'parsed': BaseModel | None}
        """
        if not self.tools:
            # No tools registered, fall back to standard run
            return await self.run(user_message)

        cfg = _get_config()
        system = self._system_prompt()

        # Add tool descriptions to system prompt
        tool_desc = self.tools.to_text_description()
        system = f"{system}\n\n---\n{tool_desc}"

        # Build conversation
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]

        full_conversation = []  # Track all reasoning for final output
        raw_text = ""  # Will hold last LLM response

        for iteration in range(max_iterations):
            logger.debug(f"{self.name} ReAct iteration {iteration + 1}/{max_iterations}")

            try:
                if cfg["sdk"] == "anthropic":
                    raw_text = await self._call_anthropic(cfg, system, messages[-1]["content"])
                else:
                    raw_text = await self._call_openai(cfg, system, messages[-1]["content"])
            except Exception as e:
                err_msg = str(e).lower()
                if "timeout" in err_msg or "timed out" in err_msg:
                    raise AgentTimeoutError(f"{self.name} ReAct timed out: {e}")
                raise AgentAPIError(f"{self.name} ReAct API error: {e}")

            full_conversation.append(f"--- Iteration {iteration + 1} ---\n{raw_text}")

            # Parse tool calls from output
            tool_calls = self._extract_tool_calls(raw_text)

            if not tool_calls:
                # No tool calls — this is the final answer
                logger.debug(f"{self.name} ReAct: final answer at iteration {iteration + 1}")
                break

            # Execute tools and build observation
            observations = []
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})

                tool = self.tools.get(tool_name)
                if not tool:
                    observations.append(f"Tool '{tool_name}' not found. Available: {[t.name for t in self.tools.list_tools()]}")
                    continue

                logger.info(f"{self.name} calling tool: {tool_name}({tool_args})")
                result = await tool.execute(**tool_args)
                observations.append(f"Tool `{tool_name}` result:\n{result}")

            # Append observation and continue loop
            obs_text = "\n\n".join(observations)
            full_conversation.append(f"--- Tool Results ---\n{obs_text}")

            messages.append({"role": "assistant", "content": raw_text})
            messages.append({"role": "user", "content": f"Tool results:\n{obs_text}\n\nContinue your reasoning or provide your final answer."})

        # Combine all reasoning for the raw output
        combined_raw = "\n\n".join(full_conversation)

        # Parse final output (last LLM response)
        # Strip tool_call blocks before parsing to avoid extracting tool JSON
        parsed = None
        if self.output_schema and raw_text:
            try:
                # Remove tool_call blocks from the final response
                import re as _re
                clean = _re.sub(r'```tool_call\s*\n.*?\n```', '', raw_text, flags=_re.DOTALL)
                clean = _re.sub(r'```tool\s*\n.*?\n```', '', clean, flags=_re.DOTALL)
                clean = clean.strip()
                if clean.startswith("```"):
                    first_line_end = clean.index("\n") if "\n" in clean else len(clean)
                    clean = clean[first_line_end + 1:] if first_line_end < len(clean) else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
                clean = _extract_json_object(clean)
                parsed = self.output_schema.model_validate_json(clean)
            except Exception as e:
                logger.warning(f"{self.name} ReAct schema validation failed: {e}")
                raise AgentVerificationError(
                    f"{self.name} ReAct output failed schema validation: {e}"
                )

        return {"raw": combined_raw, "parsed": parsed}

    def _extract_tool_calls(self, text: str) -> list[dict]:
        """Extract tool calls from LLM output.

        Looks for ```tool_call blocks with JSON, or standalone JSON objects
        with 'name' and 'args' keys.
        """
        calls = []

        # Pattern 1: ```tool_call ... ``` blocks
        pattern = r'```tool_call\s*\n(.*?)\n```'
        matches = re.findall(pattern, text, re.DOTALL)
        for m in matches:
            try:
                tc = json.loads(m.strip())
                if "name" in tc:
                    calls.append(tc)
            except json.JSONDecodeError:
                pass

        # Pattern 2: ```tool ... ``` blocks (shorter alias)
        if not calls:
            pattern2 = r'```tool\s*\n(.*?)\n```'
            matches2 = re.findall(pattern2, text, re.DOTALL)
            for m in matches2:
                try:
                    tc = json.loads(m.strip())
                    if "name" in tc:
                        calls.append(tc)
                except json.JSONDecodeError:
                    pass

        return calls
