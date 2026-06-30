"""
agent.py — wrapper generik untuk satu agent.
Load soul.md sebagai system prompt, panggil LLM via OpenAI-compatible API,
optionally parse ke pydantic schema.

Support semua provider: Xpiki, UniModel, Xiaomi, Conduit, OpenRouter, dll.
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

# Config dari env — user isi manual saat start
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.xpiki.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "kr/claude-opus-4.8")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))


class AgentTimeoutError(Exception):
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
        self._client = self._build_client()

    def _load_soul(self) -> str:
        if not self.soul_path.exists():
            raise FileNotFoundError(f"Soul file not found: {self.soul_path}")
        return self.soul_path.read_text(encoding="utf-8")

    def _build_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            timeout=self.timeout_s,
        )

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

    async def run(self, user_message: str) -> dict:
        """Returns {'raw': str, 'parsed': BaseModel | None}"""
        try:
            response = await self._client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": user_message},
                ],
            )
        except Exception as e:
            raise AgentTimeoutError(f"{self.name} failed: {e}")

        raw_text = response.choices[0].message.content or ""

        parsed = None
        if self.output_schema:
            try:
                clean = raw_text.strip()
                # Strip markdown code fences if present
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
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
