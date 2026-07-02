"""Admin endpoints for triggering and inspecting the background agents."""

import asyncio
import logging

from fastapi import APIRouter

from backend.agents.citation_agent import citation_agent
from backend.agents.embedding_agent import embedding_agent
from backend.agents.extraction_agent import extraction_agent
from backend.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Strong references to in-flight background tasks. asyncio only keeps weak refs,
# so without this a detached task can be garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


@router.post("/agents/citation/run")
async def run_citation_agent():
    """Trigger the CitationAgent in the background and return immediately.

    A full batch involves many NCBI + LLM calls, so it runs detached; poll
    /admin/agents/citation/log for the resulting CitationRun entries.
    """
    batch_size = settings.CITATION_AGENT_BATCH_SIZE

    async def _runner():
        try:
            await citation_agent.run(batch_size=batch_size)
        except Exception as exc:  # noqa: BLE001
            logger.exception("CitationAgent background run failed: %s", exc)

    task = asyncio.create_task(_runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started", "batch_size": batch_size}


@router.get("/agents/citation/log")
async def citation_agent_log():
    """Return the last 10 CitationRun log entries."""
    return await citation_agent.recent_runs(limit=10)


@router.post("/agents/embedding/run")
async def run_embedding_agent():
    """Trigger the EmbeddingAgent in the background and return immediately.

    Each node calls the OpenRouter embedding API, so a batch runs detached; poll
    /admin/agents/embedding/log for the resulting EmbeddingRun entries.
    """
    batch_size = settings.EMBEDDING_AGENT_BATCH_SIZE

    async def _runner():
        try:
            await embedding_agent.run(batch_size=batch_size)
        except Exception as exc:  # noqa: BLE001
            logger.exception("EmbeddingAgent background run failed: %s", exc)

    task = asyncio.create_task(_runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started", "batch_size": batch_size}


@router.get("/agents/embedding/log")
async def embedding_agent_log():
    """Return the last 10 EmbeddingRun log entries."""
    return await embedding_agent.recent_runs(limit=10)


@router.post("/agents/extraction/run")
async def run_extraction_agent():
    """Trigger the literature ExtractionAgent (Feature 2) in the background.

    GATED: returns 'disabled' unless EXTRACTION_AGENT_ENABLED is true, because a run
    spends on NCBI E-utils + the LLM. Proposals land as CandidateEdge nodes (never
    trusted topology — ADR-0013); review via /admin/agents/extraction/candidates.
    """
    if not settings.EXTRACTION_AGENT_ENABLED:
        return {"status": "disabled",
                "detail": "set EXTRACTION_AGENT_ENABLED=true to run the extractor"}

    async def _runner():
        try:
            await extraction_agent.run()
        except Exception as exc:  # noqa: BLE001
            logger.exception("ExtractionAgent background run failed: %s", exc)

    task = asyncio.create_task(_runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started"}


@router.get("/agents/extraction/candidates")
async def extraction_candidates(limit: int = 50):
    """Pending CandidateEdges at/above the confidence floor, strongest first."""
    return await extraction_agent.list_candidates(limit=limit)


@router.get("/agents/extraction/log")
async def extraction_agent_log():
    """Return the last 10 ExtractionRun log entries."""
    return await extraction_agent.recent_runs(limit=10)
