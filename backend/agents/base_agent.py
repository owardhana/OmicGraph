"""Shared agent infrastructure: provenance, retry, and run logging.

Every agent write carries provenance (source_agent, agent_version, run_timestamp)
per the agent safety rules in AGENTS.md.
"""

import asyncio
import logging
from datetime import datetime, timezone

from backend.db.neo4j_client import get_session

logger = logging.getLogger(__name__)


class BaseAgent:
    agent_name: str = "BaseAgent"
    agent_version: str = "0.1.0"

    def provenance(self) -> dict:
        """Provenance stamp attached to every agent-written node/edge."""
        return {
            "source_agent": self.agent_name,
            "agent_version": self.agent_version,
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def retry(self, func, *args, n: int = 2, **kwargs):
        """Await func with up to n retries (n+1 attempts) and backoff."""
        last_exc: Exception | None = None
        for attempt in range(n + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "%s: attempt %d/%d failed: %s",
                    self.agent_name, attempt + 1, n + 1, exc,
                )
                if attempt < n:
                    await asyncio.sleep(0.5 * (attempt + 1))
        assert last_exc is not None
        raise last_exc

    async def write_run_log_to_graph(self, label: str, props: dict) -> None:
        """Create an operational log node (e.g. CitationRun) with provenance.

        label is an internal constant, never user input. Log nodes are
        operational metadata and are distinct from biological Gene/Transcript
        nodes — agents never create biological topology.
        """
        full_props = {**props, **self.provenance()}
        async with get_session() as session:
            await session.run(f"CREATE (n:{label}) SET n = $props", props=full_props)
        logger.info("%s: wrote %s log node: %s", self.agent_name, label, props)
