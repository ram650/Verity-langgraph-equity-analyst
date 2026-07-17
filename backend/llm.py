"""
One place to talk to Claude. Loads the API key from .env, exposes a simple
call() that returns (text, usage). Centralizing this means we switch models
(Haiku for cheap dev, Sonnet for quality) in exactly one spot.
"""

import os
import json
import httpx
from dotenv import load_dotenv
import anthropic

load_dotenv()                     # reads ANTHROPIC_API_KEY from backend/.env
# Force IPv4. Some hosts (e.g. Render) have broken IPv6 egress, and httpx
# preferring IPv6 for api.anthropic.com then fails with APIConnectionError.
_client = anthropic.Anthropic(
    http_client=httpx.Client(
        transport=httpx.HTTPTransport(local_address="0.0.0.0"),  # bind IPv4
        timeout=httpx.Timeout(600.0, connect=15.0),
    )
)

# Cheap default while we build. Bump to "claude-sonnet-5" for final quality.
DEFAULT_MODEL = "claude-haiku-4-5"


def _messages(prompt: str, cache_context: str | None):
    """Build the messages list. If cache_context is given, put it first as a
    cached block so later calls with the same prefix reuse it at ~10% cost."""
    if cache_context:
        return [{"role": "user", "content": [
            {"type": "text", "text": cache_context,
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": prompt},
        ]}]
    return [{"role": "user", "content": prompt}]


def call(prompt: str, system: str | None = None, model: str = DEFAULT_MODEL,
         max_tokens: int = 600, cache_context: str | None = None):
    """Send one prompt, return (text, usage)."""
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": _messages(prompt, cache_context),
    }
    if system:
        kwargs["system"] = system
    resp = _client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, resp.usage


def call_json(prompt: str, schema: dict, system: str | None = None,
              model: str = DEFAULT_MODEL, max_tokens: int = 900,
              cache_context: str | None = None):
    """Like call(), but forces the model to return JSON matching `schema`.
    The API constrains the output, so json.loads() can't fail on rambling."""
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": _messages(prompt, cache_context),
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }
    if system:
        kwargs["system"] = system
    resp = _client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if b.type == "text")
    if not text.strip():
        # e.g. Sonnet's adaptive thinking ate the whole max_tokens budget.
        raise ValueError(f"Empty response (stop_reason={resp.stop_reason}); "
                         "likely truncated — raise max_tokens.")
    return json.loads(text), resp.usage
