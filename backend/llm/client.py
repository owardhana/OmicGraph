"""OpenRouter LLM client (OpenAI-compatible).

A single AsyncOpenAI client pointed at OpenRouter. Model slugs come from config
(verified canonical OpenRouter slugs — see docs/adr/0002-openrouter-model-slugs.md).
"""

import asyncio
import logging

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from backend.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Statuses worth another attempt: provider congestion, upstream hiccups, timeouts. The
# free Nemotron endpoint returns 429 ("Worker local total request limit reached") under
# load, which clears on its own. 401/402/403 are NOT here — a bad key or an empty credit
# balance never fixes itself by retrying.
_TRANSIENT_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})

SYNTHESIS_MODEL = settings.SYNTHESIS_MODEL
CITATION_CHECK_MODEL = settings.CITATION_CHECK_MODEL

_EMBED_MAX_CHARS = 8000  # keep well under the embedding model's token limit

_client: AsyncOpenAI | None = None


def reasoning_model_kwargs() -> dict:
    """Defensive completion kwargs shared by both callers of the free reasoning model
    (the extraction relation verdict and the citation-relevance check — both now run on
    the same Nemotron slug):

    - ``timeout`` — a bounded per-call budget. A free/reasoning model can stream very
      slowly or sit queued, and the OpenAI SDK default is ~10 min; a timeout raises,
      which callers treat as a transient/retryable error rather than a silent hang.
    - ``reasoning.exclude`` — drop the chain-of-thought preamble so the JSON parser sees
      clean output. No-op on non-reasoning models; gated on ``EXTRACTION_EXCLUDE_REASONING``.
    """
    kwargs: dict = {"timeout": settings.EXTRACTION_LLM_TIMEOUT_S}
    if settings.EXTRACTION_EXCLUDE_REASONING:
        kwargs["extra_body"] = {"reasoning": {"exclude": True}}
    return kwargs


def status_of(exc: Exception) -> int | None:
    """The HTTP-ish status behind an OpenAI SDK error, from wherever it actually landed.

    Two different shapes reach us and only one has ``status_code``:

    - a failure on the response envelope -> ``APIStatusError``, ``.status_code`` set;
    - a failure delivered *inside* an HTTP 200 stream -> a bare ``APIError`` with no
      ``.status_code`` at all; the real code sits in ``.code`` / ``.body['code']``.
      This is OpenRouter's shape for an upstream provider fault, e.g.
      ``{'code': 502, 'message': 'Upstream error from Nvidia: ResourceExhausted:
      Worker local total request limit reached (33/32)'}``.

    Reading only ``status_code`` classifies every mid-stream provider hiccup as
    permanent, which is exactly backwards — those are the ones that clear on retry."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    for candidate in (getattr(exc, "code", None),
                      (getattr(exc, "body", None) or {}).get("code")
                      if isinstance(getattr(exc, "body", None), dict) else None):
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def is_transient(exc: Exception) -> bool:
    """True if ``exc`` is worth retrying, False if retrying can only fail the same way.

    The distinction is user-visible: a congested free endpoint (429/502) clears, so
    "try again" is honest advice; a 402 (out of credits) or 401 (bad key) does not, and
    telling someone to retry one of those just sends them round a loop."""
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return True
    status = status_of(exc)
    return status is not None and status in _TRANSIENT_STATUS


def chat_model_kwargs() -> dict:
    """Defensive completion kwargs for the interactive chat turn.

    SYNTHESIS_MODEL now points at the same free Nemotron slug as extraction, so the chat
    stream needs comparable guards to reasoning_model_kwargs — but with chat-scoped
    values, because a batch budget is the wrong shape for a stream someone is watching:

    - ``timeout`` — CHAT_LLM_TIMEOUT_S, not the 120 s extraction budget.
    - ``max_tokens`` — the free slug advertises a 1M-token context; an uncapped reasoning
      model on that window is a latency and runaway-output hazard mid-stream.
    - ``reasoning.exclude`` — keep the chain-of-thought preamble out of the token stream,
      so it can't surface as ``<think>`` text in the user's answer.
    """
    kwargs: dict = {
        "timeout": settings.CHAT_LLM_TIMEOUT_S,
        "max_tokens": settings.CHAT_MAX_TOKENS,
    }
    if settings.CHAT_EXCLUDE_REASONING:
        kwargs["extra_body"] = {"reasoning": {"exclude": True}}
    return kwargs


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
        )
    return _client


async def embed_text(text: str) -> list[float]:
    """Embed a single text with the configured embedding model (ADR-0008).

    Shared by the EmbeddingAgent (batch node enrichment) and the chat
    ``semantic_search`` tool (embedding the live query). Each call hits the
    OpenRouter embeddings API — cheap, but not free."""
    response = await get_client().embeddings.create(
        model=settings.EMBEDDING_MODEL, input=text[:_EMBED_MAX_CHARS]
    )
    return response.data[0].embedding


async def complete(model: str, messages: list[dict], **kwargs) -> str:
    """Run a chat completion and return the assistant text (never None).

    OpenRouter can return an HTTP 200 whose body carries ``choices: null`` plus an
    ``error`` (e.g. an upstream free-tier rate limit) instead of raising. Guard against
    that so it surfaces as a retryable exception rather than a bare
    ``'NoneType' object is not subscriptable`` — callers treat exceptions as transient
    (retry/backoff) and unparseable *text* as a drop, so this must raise, not return ""."""
    response = await get_client().chat.completions.create(
        model=model, messages=messages, **kwargs
    )
    if not response.choices:
        err = getattr(response, "error", None)
        raise RuntimeError(f"completion returned no choices (model={model}): {err or response}")
    return response.choices[0].message.content or ""


async def stream_chat(model: str, messages: list[dict], tools: list[dict] | None = None):
    """Stream one turn. Yields ('text', delta) for content tokens, then a final
    ('message', {role, content, tool_calls}) once the turn completes — so the caller
    can forward tokens live AND inspect tool_calls to drive the agent loop. Tool-call
    fragments arrive as indexed deltas and are reassembled here.

    Retries a transient failure (the free endpoint's 429s, timeouts) up to
    CHAT_LLM_MAX_RETRIES times, but ONLY while no text has been yielded yet: once a
    token reaches the caller it has already reached the user's screen, and a fresh
    attempt would restart the answer mid-sentence. Tool-call fragments are safe to
    discard on retry — they are not surfaced until the closing ('message', ...)."""
    kwargs: dict = {"model": model, "messages": messages, "stream": True,
                    **chat_model_kwargs()}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    attempts = settings.CHAT_LLM_MAX_RETRIES + 1
    for attempt in range(attempts):
        content_parts: list[str] = []
        tool_acc: dict[int, dict] = {}  # index -> {id, name, arguments(str)}
        streamed_text = False  # once True, this turn can no longer be restarted
        try:
            stream = await get_client().chat.completions.create(**kwargs)
            async for chunk in stream:
                # OpenRouter interleaves keep-alive / usage-only frames that carry no
                # choices; indexing [0] on those raises IndexError mid-stream.
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content_parts.append(delta.content)
                    streamed_text = True
                    yield ("text", delta.content)
                for tc in (delta.tool_calls or []):
                    slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
        except Exception as exc:  # noqa: BLE001 — classified below, then re-raised
            if streamed_text or not is_transient(exc) or attempt == attempts - 1:
                raise
            backoff = settings.EXTRACTION_HTTP_BACKOFF_S * (2 ** attempt)
            logger.warning(
                "stream_chat: attempt %d/%d failed (%s); retrying in %.1fs",
                attempt + 1, attempts, exc, backoff,
            )
            await asyncio.sleep(backoff)
            continue

        calls = [tool_acc[i] for i in sorted(tool_acc)]
        yield ("message", {
            "role": "assistant",
            "content": "".join(content_parts) or None,
            "tool_calls": calls,
        })
        return
