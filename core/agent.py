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
from pathlib import Path
from typing import Optional, Type
from pydantic import BaseModel
from openai import AsyncOpenAI

logger = logging.getLogger("agent")

SOULS_DIR = Path(__file__).parent.parent / "souls"


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
        "base_url": "https://api.xiaomi.com/v1",
        "default_model": "mimo-v2.5",
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
    "openai-compatible": {
        # Generic fallback for Xpiki, Conduit, etc.
        "base_url": None,  # must be set via LLM_BASE_URL
        "default_model": None,  # must be set via LLM_MODEL
        "sdk": "openai",
    },
}


def _get_config() -> dict:
    """Lazy config — reads .env every call, so values are always current."""
    provider_name = os.getenv("LLM_PROVIDER", "openrouter").lower()
    provider = PROVIDERS.get(provider_name, PROVIDERS["openai-compatible"])

    base_url = os.getenv("LLM_BASE_URL", provider["base_url"] or "")
    model = os.getenv("LLM_MODEL", provider["default_model"] or "")
    api_key = os.getenv("LLM_API_KEY", "")

    return {
        "provider": provider_name,
        "sdk": provider["sdk"],
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
    ):
        self.name = name
        self.soul_path = SOULS_DIR / soul_file
        self.technical_prompt = technical_prompt
        self.output_schema = output_schema
        self.timeout_s = timeout_s
        self._soul_text = self._load_soul()
        self._client = None  # lazy init per-run to pick up latest config

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
                parsed = self.output_schema.model_validate_json(clean)
            except Exception as e:
                logger.warning(f"{self.name} schema validation failed: {e}")
                raise AgentVerificationError(
                    f"{self.name} output failed schema validation: {e}"
                )

        return {"raw": raw_text, "parsed": parsed}
