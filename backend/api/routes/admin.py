"""Admin endpoints for triggering and inspecting the background agents."""

import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.agents.citation_agent import citation_agent
from backend.agents.embedding_agent import embedding_agent
from backend.agents.extraction_agent import extraction_agent
from backend.agents.validation_agent import validation_agent
from backend.config import settings
from backend.db.neo4j_client import get_session
from backend.extraction import review

logger = logging.getLogger(__name__)


async def _require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate the whole /admin router on ADMIN_TOKEN (ADR-0014 §3). Empty token = open
    (local single-user dev); set it on any shared/public host."""
    if settings.ADMIN_TOKEN and x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing X-Admin-Token")


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(_require_admin)])

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


# --- ValidationAgent: promotion gate (Feature 2 P2, ADR-0013) ---------------
# All writes are gated on the feature master switch. Auto-promote is *further* gated
# inside the agent by VALIDATION_AUTO_PROMOTE_ENABLED (uncalibrated -> default off).

@router.post("/agents/validation/run")
async def run_validation_agent():
    """Run the auto-promote pass. Gated on EXTRACTION_AGENT_ENABLED; a no-op unless
    VALIDATION_AUTO_PROMOTE_ENABLED is also true (promotion writes trusted topology)."""
    if not settings.EXTRACTION_AGENT_ENABLED:
        return {"status": "disabled",
                "detail": "set EXTRACTION_AGENT_ENABLED=true to run validation"}

    async def _runner():
        try:
            await validation_agent.run()
        except Exception as exc:  # noqa: BLE001
            logger.exception("ValidationAgent background run failed: %s", exc)

    task = asyncio.create_task(_runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started"}


@router.get("/candidates")
async def review_candidates(status: str = "pending", sort: str = "confidence",
                            limit: int = 100):
    """Review queue for one status tab (pending|promoted|rejected). Unlike
    /agents/extraction/candidates this is NOT confidence-gated (ADR-0014 §4) — the
    sub-floor candidates are the whole reason manual review exists."""
    async with get_session() as session:
        return await review.list_for_review(session, status=status, sort=sort, limit=limit)


@router.get("/candidates/{triple_key}")
async def review_candidate_detail(triple_key: str):
    """Full review payload: resolved endpoints, evidence chain, would_be_action, agent
    profiling (ADR-0014 detail shape)."""
    async with get_session() as session:
        detail = await review.candidate_detail(session, triple_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return detail


@router.post("/candidates/{triple_key}/revert")
async def revert_candidate(triple_key: str):
    """Undo a promotion (ADR-0014 §2) — delete a minted literature edge, or strip the
    exact enrichment delta; the candidate returns to the pending queue."""
    if not settings.EXTRACTION_AGENT_ENABLED:
        return {"status": "disabled",
                "detail": "set EXTRACTION_AGENT_ENABLED=true to revert promotions"}
    return await validation_agent.revert(triple_key)


@router.post("/candidates/{triple_key}/approve")
async def approve_candidate(triple_key: str):
    """Manually promote a pending candidate to a trusted (literature-tier) edge."""
    if not settings.EXTRACTION_AGENT_ENABLED:
        return {"status": "disabled",
                "detail": "set EXTRACTION_AGENT_ENABLED=true to promote candidates"}
    return await validation_agent.approve(triple_key)


@router.post("/candidates/{triple_key}/reject")
async def reject_candidate(triple_key: str):
    """Reject a candidate (kept + flagged, never re-proposed)."""
    if not settings.EXTRACTION_AGENT_ENABLED:
        return {"status": "disabled",
                "detail": "set EXTRACTION_AGENT_ENABLED=true to reject candidates"}
    return await validation_agent.reject(triple_key)


@router.get("/agents/validation/log")
async def validation_agent_log():
    """Return the last 10 ValidationRun log entries."""
    return await validation_agent.recent_runs(limit=10)
