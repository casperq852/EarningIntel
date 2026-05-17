"""
Unified LLM caller — Anthropic native SDK or OpenRouter (OpenAI-compatible).
Returns parsed JSON dict. Handles retries with exponential backoff.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, Optional

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


async def call_llm(
    system: str,
    prompt: str,
    *,
    provider: str = "anthropic",
    model: str = "claude-sonnet-4-20250514",
    anthropic_api_key: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    max_tokens: int = 4096,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Call an LLM and return the parsed JSON response dict."""
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            raw = await _call_once(
                system, prompt,
                provider=provider,
                model=model,
                anthropic_api_key=anthropic_api_key,
                openrouter_api_key=openrouter_api_key,
                max_tokens=max_tokens,
            )
            raw = raw.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
            raw = re.sub(r"\s*```$", "", raw.strip())
            return json.loads(raw)
        except Exception as e:
            last_error = e
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_error}")


async def _call_once(
    system: str,
    prompt: str,
    *,
    provider: str,
    model: str,
    anthropic_api_key: Optional[str],
    openrouter_api_key: Optional[str],
    max_tokens: int,
) -> str:
    if provider == "openrouter":
        from openai import AsyncOpenAI
        key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not configured in settings or environment")
        client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content or ""
    else:
        import anthropic as ant
        key = anthropic_api_key or _ANTHROPIC_API_KEY
        client = ant.AsyncAnthropic(api_key=key)
        msg = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
