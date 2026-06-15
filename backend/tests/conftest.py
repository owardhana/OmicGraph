"""Pytest fixtures. Tests run against the live Neo4j at NEO4J_URI (.env)."""

import pytest_asyncio

from backend.db.neo4j_client import close_driver, get_session
from backend.db.queries.genes import get_gene_by_symbol


@pytest_asyncio.fixture
async def neo4j_session():
    async with get_session() as session:
        yield session


@pytest_asyncio.fixture
async def sample_gene():
    """The TP53 gene record ({'props': {...}, 'is_tf': bool})."""
    return await get_gene_by_symbol("TP53")


@pytest_asyncio.fixture
async def sample_edge(neo4j_session):
    """One REGULATES edge: {src, tgt, eid}."""
    rows = await (
        await neo4j_session.run(
            """
            MATCH (s:Gene)-[r:REGULATES]->(t:Gene)
            RETURN s.hgnc_symbol AS src, t.hgnc_symbol AS tgt, elementId(r) AS eid
            LIMIT 1
            """
        )
    ).data()
    return rows[0]


@pytest_asyncio.fixture(autouse=True)
async def _fresh_driver_per_test():
    """Close the shared async driver after each test.

    pytest-asyncio gives each test its own event loop; the module-level Neo4j
    AsyncDriver binds to the loop it was created on. Closing it after every test
    forces a fresh driver on the next test's loop, avoiding "future attached to a
    different loop" errors.
    """
    yield
    await close_driver()
