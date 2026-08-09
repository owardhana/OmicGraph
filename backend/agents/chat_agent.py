"""ChatAgent — agentic, tool-using, streaming conversational assistant (Feature 1).

A multi-turn, tool-using agent loop:

  load history -> [system, ...history, user] -> stream an LLM turn -> if it asked for
  tools, run them (read-only), append results, loop -> else stream the final answer.

Memory: prior user/assistant turns are loaded from / saved to Neo4j (db/queries/chat).
Streaming: ``run_stream`` is an async generator of event dicts the SSE route forwards
({type: token|tool|done|error}). Read-only throughout — the tools never write; there
is no write path.
"""

import logging

from backend.agents.tools import TOOL_SCHEMAS, dispatch_tool
from backend.db.queries.chat import load_history, save_turn
from backend.llm.client import (
    SYNTHESIS_MODEL,
    is_daily_free_cap,
    is_transient,
    status_of,
    stream_chat,
)
from backend.llm.prompts.chat import CHAT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_MAX_TOOL_ITERS = 6  # safety cap on the tool loop (each iter = one LLM turn)


def _error_message(exc: Exception) -> str:
    """User-facing text for a failed turn.

    "Please retry" has to be earned. The chat model runs on a free, shared endpoint
    where congestion is the common failure and does clear — but a 402 (out of credits)
    or 401 (bad key) will fail identically forever, and telling someone to retry one of
    those sends them into a loop instead of to the actual fix."""
    status = status_of(exc)
    if status in (401, 402, 403):
        return ("The assistant is unavailable — the LLM account needs attention "
                "(API key or billing). Retrying won't help.")
    # Checked before the generic transient branch: this one IS a 429, but it clears at
    # 00:00 UTC rather than in seconds, so "try again in a moment" would be a lie.
    if is_daily_free_cap(exc):
        return ("The free-model daily quota for this deployment is used up. It resets "
                "at 00:00 UTC — the assistant will work again after that.")
    if is_transient(exc):
        return ("The model endpoint is busy right now. Please try again in a moment.")
    return "The assistant hit an error. Please retry."


def _assistant_msg(msg: dict) -> dict:
    """Normalised {content, tool_calls} -> OpenAI assistant message for the next call."""
    out: dict = {"role": "assistant", "content": msg.get("content")}
    if msg.get("tool_calls"):
        out["tool_calls"] = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in msg["tool_calls"]
        ]
    return out


class ChatAgent:
    agent_name = "ChatAgent"
    agent_version = "0.1.0"

    async def run_stream(self, session_id: str, question: str, tissue: str = "all"):
        """Yield event dicts: {type:'token',text} | {type:'tool',name,status} |
        {type:'done',answer} | {type:'error',message}."""
        history = await load_history(session_id)
        messages: list[dict] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
        messages += [{"role": h["role"], "content": h["content"]} for h in history]
        user_content = question if tissue in (None, "", "all") else (
            f"{question}\n(Focus on the '{tissue}' tissue where relevant.)"
        )
        messages.append({"role": "user", "content": user_content})

        answer_parts: list[str] = []
        answered = False
        try:
            for _ in range(_MAX_TOOL_ITERS):
                final_msg: dict | None = None
                async for kind, payload in stream_chat(SYNTHESIS_MODEL, messages, TOOL_SCHEMAS):
                    if kind == "text":
                        answer_parts.append(payload)
                        yield {"type": "token", "text": payload}
                    elif kind == "message":
                        final_msg = payload

                if not final_msg or not final_msg.get("tool_calls"):
                    answered = True
                    break  # no tool calls -> the streamed text was the final answer

                # Run the requested tools, append assistant + tool messages, loop.
                messages.append(_assistant_msg(final_msg))
                for call in final_msg["tool_calls"]:
                    yield {"type": "tool", "name": call["name"], "status": "running"}
                    result = await dispatch_tool(call["name"], call["arguments"])
                    yield {"type": "tool", "name": call["name"], "status": "done"}
                    messages.append({
                        "role": "tool", "tool_call_id": call["id"], "content": result,
                    })

            # Tool budget exhausted without a final answer -> force one final turn with
            # NO tools, so a complex query still concludes instead of cutting off mid-loop.
            if not answered:
                messages.append({
                    "role": "user",
                    "content": "Give your final answer now from the tool results above; "
                               "do not call any more tools.",
                })
                async for kind, payload in stream_chat(SYNTHESIS_MODEL, messages, None):
                    if kind == "text":
                        answer_parts.append(payload)
                        yield {"type": "token", "text": payload}
        except Exception as exc:  # noqa: BLE001 — surface a clean error, don't 500 mid-stream
            logger.warning("ChatAgent stream failed: %s", exc)
            yield {"type": "error", "message": _error_message(exc)}
            return

        answer = "".join(answer_parts).strip()
        await save_turn(session_id, "user", question)
        await save_turn(session_id, "assistant", answer)
        yield {"type": "done", "answer": answer}


chat_agent = ChatAgent()
