"""Agentic chatbot endpoint (Feature 1).

POST /api/chat/stream  — Server-Sent Events: token / tool / done / error frames as the
                         agent works, so the UI shows tokens and "running search_graph…".

POST (not EventSource/GET) so the body carries session_id + message; the frontend reads
the response body as a stream.
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.agents.chat_agent import chat_agent
from backend.api.models import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def event_gen():
        async for event in chat_agent.run_stream(
            request.session_id, request.message, request.tissue
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
