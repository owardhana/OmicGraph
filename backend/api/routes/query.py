"""Natural-language query endpoint (Text2Cypher via QueryAgent)."""

from fastapi import APIRouter

from backend.agents.query_agent import query_agent
from backend.api.models import QueryRequest, QueryResponse

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def run_query(request: QueryRequest):
    return await query_agent.query(
        request.question, tissue=request.tissue, max_hops=request.max_hops
    )
