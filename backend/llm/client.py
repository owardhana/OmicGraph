"""OpenRouter LLM client (OpenAI-compatible).

A single AsyncOpenAI client pointed at OpenRouter. Model slugs come from config
(verified canonical OpenRouter slugs — see docs/adr/0002-openrouter-model-slugs.md).
"""

from openai import AsyncOpenAI

from backend.config import settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TEXT2CYPHER_MODEL = settings.TEXT2CYPHER_MODEL
SYNTHESIS_MODEL = settings.SYNTHESIS_MODEL
CITATION_CHECK_MODEL = settings.CITATION_CHECK_MODEL

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
        )
    return _client


async def complete(model: str, messages: list[dict], **kwargs) -> str:
    """Run a chat completion and return the assistant text (never None)."""
    response = await get_client().chat.completions.create(
        model=model, messages=messages, **kwargs
    )
    return response.choices[0].message.content or ""
