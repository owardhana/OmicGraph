"""Cypher safety validation for LLM-generated queries.

Two gates, both must pass before any LLM Cypher is executed:
  1. Static: reject any query containing a write keyword (read-only enforcement).
  2. Dynamic: EXPLAIN the query (dry-run, never executes) to catch syntax errors.
"""

import logging
import re

from backend.db.neo4j_client import get_session

logger = logging.getLogger(__name__)

# Write / DDL keywords that must never appear in a query the agent will execute.
_WRITE_KEYWORDS = re.compile(
    r"\b(MERGE|CREATE|DELETE|SET|REMOVE|DROP|DETACH|LOAD\s+CSV|FOREACH|CALL\s*\{[^}]*})\b",
    re.IGNORECASE,
)
# A bare write-procedure call, e.g. CALL apoc.create.*, db.create*, etc.
_WRITE_PROC = re.compile(r"\bCALL\s+[\w.]*\b(create|merge|delete|set|drop)\w*",
                         re.IGNORECASE)


def has_write_operation(query: str) -> bool:
    return bool(_WRITE_KEYWORDS.search(query) or _WRITE_PROC.search(query))


async def validate_cypher(query: str) -> bool:
    """Return True only if the query is non-empty, read-only, and EXPLAIN-able."""
    if not query or not query.strip():
        logger.warning("validate_cypher: empty query")
        return False
    if has_write_operation(query):
        logger.warning("validate_cypher: blocked write operation in query: %s", query)
        return False
    try:
        async with get_session() as session:
            await session.run(f"EXPLAIN {query}")
        return True
    except Exception as exc:  # noqa: BLE001 - any planner error means invalid
        logger.warning("validate_cypher: EXPLAIN failed: %s", exc)
        return False
