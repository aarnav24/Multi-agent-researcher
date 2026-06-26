"""Neo4j adapter for the Citation Graph (Layer C).

Manages connection lifecycle, schema setup, and provides async-compatible
Cypher query execution using the native neo4j 6.x async driver.
Includes connection retry, query timeout, and parameterization validation.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Singleton driver instance (AsyncGraphDatabase)
_driver = None

# Query timeout in seconds
QUERY_TIMEOUT = 30.0

# Connection retry settings
CONNECT_MAX_RETRIES = 3
CONNECT_RETRY_DELAY = 2.0


def _validate_query(query: str) -> None:
    """Validate that query uses parameterized values, not string interpolation.

    Raises ValueError if query appears to use f-string interpolation without $params.
    """
    # Check for f-string-style interpolation: {variable} without $param
    if re.search(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}', query) and '$' not in query:
        raise ValueError(
            "Query appears to use string interpolation instead of $parameters. "
            "Use parameterized queries to prevent Cypher injection."
        )


async def _run_cypher(query: str, parameters: dict | None = None, timeout: float = QUERY_TIMEOUT) -> list[dict]:
    """Run a Cypher query using the native async driver with timeout.

    Validates query parameterization before execution.
    """
    global _driver
    if _driver is None:
        raise RuntimeError("Neo4j not connected. Call connect() first.")

    _validate_query(query)

    async with _driver.session(database=settings.neo4j_database) as session:
        result = await asyncio.wait_for(
            session.run(query, parameters or {}),
            timeout=timeout,
        )
        return [record.data() async for record in result]


async def connect(max_retries: int = CONNECT_MAX_RETRIES, retry_delay: float = CONNECT_RETRY_DELAY) -> bool:
    """Initialize the Neo4j driver and create constraints/indexes with retry."""
    global _driver
    try:
        from neo4j import AsyncGraphDatabase
    except ImportError:
        logger.warning("Neo4j: neo4j package not installed, citation graph disabled")
        return False

    for attempt in range(max_retries):
        try:
            _driver = AsyncGraphDatabase.driver(
                settings.neo4j_url,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            # Verify connectivity
            async with _driver.session(database=settings.neo4j_database) as session:
                await session.run("RETURN 1")

            # Create constraints and indexes
            await _create_schema()
            logger.info("Neo4j: connected and schema ready")
            return True
        except Exception as e:
            logger.warning(f"Neo4j: connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))

    logger.warning(f"Neo4j: connection failed after {max_retries} attempts, citation graph disabled")
    return False


async def _create_schema():
    """Create constraints and indexes for the citation graph."""
    global _driver
    async with _driver.session(database=settings.neo4j_database) as session:
        # Constraints
        await session.run(
            "CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE"
        )
        await session.run(
            "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (s:Source) REQUIRE s.id IS UNIQUE"
        )
        await session.run(
            "CREATE CONSTRAINT subquestion_id IF NOT EXISTS FOR (q:SubQuestion) REQUIRE q.id IS UNIQUE"
        )
        # Indexes for common queries
        await session.run(
            "CREATE INDEX claim_trust IF NOT EXISTS FOR (c:Claim) ON (c.trust_score)"
        )
        await session.run(
            "CREATE INDEX source_url IF NOT EXISTS FOR (s:Source) ON (s.url)"
        )
        await session.run(
            "CREATE INDEX source_tool IF NOT EXISTS FOR (s:Source) ON (s.tool_name)"
        )


async def disconnect():
    """Close the Neo4j driver."""
    global _driver
    if _driver:
        try:
            await _driver.close()
        except Exception as e:
            logger.warning(f"Neo4j: disconnect error: {e}")
        finally:
            _driver = None
    logger.info("Neo4j: disconnected")


class Neo4jAdapter:
    """High-level adapter for citation graph operations.

    All methods are async-compatible (runs sync neo4j driver in thread pool).
    Gracefully returns empty results if Neo4j is unavailable.
    """

    def __init__(self, enabled: bool = True):
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled and _driver is not None

    async def add_claim(self, claim_id: str, text: str, trust_score: int,
                        trust_label: str, fact_check_passed: bool,
                        sub_question_id: str | None = None) -> bool:
        """Add a Claim node to the graph."""
        if not self.enabled:
            return False
        try:
            await _run_cypher(
                """
                MERGE (c:Claim {id: $id})
                SET c.text = $text,
                    c.trust_score = $trust_score,
                    c.trust_label = $trust_label,
                    c.fact_check_passed = $fact_check_passed,
                    c.sub_question_id = $sub_question_id,
                    c.updated_at = datetime()
                """,
                {
                    "id": claim_id,
                    "text": text,
                    "trust_score": trust_score,
                    "trust_label": trust_label,
                    "fact_check_passed": fact_check_passed,
                    "sub_question_id": sub_question_id,
                },
            )
            return True
        except Exception as e:
            logger.warning(f"Neo4j: add_claim failed: {e}")
            return False

    async def add_source(self, source_id: str, url: str, title: str,
                         snippet: str, domain_authority: float,
                         tool_name: str, published_date: str | None = None) -> bool:
        """Add a Source node and its URL."""
        if not self.enabled:
            return False
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            await _run_cypher(
                """
                MERGE (s:Source {id: $id})
                SET s.url = $url,
                    s.title = $title,
                    s.snippet = $snippet,
                    s.domain_authority = $domain_authority,
                    s.tool_name = $tool_name,
                    s.published_date = $published_date,
                    s.domain = $domain,
                    s.updated_at = datetime()
                """,
                {
                    "id": source_id,
                    "url": url,
                    "title": title,
                    "snippet": snippet,
                    "domain_authority": domain_authority,
                    "tool_name": tool_name,
                    "published_date": published_date,
                    "domain": domain,
                },
            )
            return True
        except Exception as e:
            logger.warning(f"Neo4j: add_source failed: {e}")
            return False

    async def add_supports_edge(self, claim_id: str, source_id: str,
                               weight: float) -> bool:
        """Add a SUPPORTS edge from claim to source."""
        if not self.enabled:
            return False
        try:
            await _run_cypher(
                """
                MATCH (c:Claim {id: $claim_id})
                MATCH (s:Source {id: $source_id})
                MERGE (c)-[r:SUPPORTS]->(s)
                SET r.weight = $weight, r.updated_at = datetime()
                """,
                {"claim_id": claim_id, "source_id": source_id, "weight": weight},
            )
            return True
        except Exception as e:
            logger.warning(f"Neo4j: add_supports_edge failed: {e}")
            return False

    async def add_contradicts_edge(self, claim_id: str, source_id: str,
                                  weight: float) -> bool:
        """Add a CONTRADICTS edge from claim to source."""
        if not self.enabled:
            return False
        try:
            await _run_cypher(
                """
                MATCH (c:Claim {id: $claim_id})
                MATCH (s:Source {id: $source_id})
                MERGE (c)-[r:CONTRADICTS]->(s)
                SET r.weight = $weight, r.updated_at = datetime()
                """,
                {"claim_id": claim_id, "source_id": source_id, "weight": weight},
            )
            return True
        except Exception as e:
            logger.warning(f"Neo4j: add_contradicts_edge failed: {e}")
            return False

    async def add_answers_edge(self, claim_id: str, sub_question_id: str) -> bool:
        """Add an ANSWERS edge from claim to sub-question."""
        if not self.enabled:
            return False
        try:
            await _run_cypher(
                """
                MATCH (c:Claim {id: $claim_id})
                MATCH (q:SubQuestion {id: $sub_question_id})
                MERGE (c)-[:ANSWERS]->(q)
                """,
                {"claim_id": claim_id, "sub_question_id": sub_question_id},
            )
            return True
        except Exception as e:
            logger.warning(f"Neo4j: add_answers_edge failed: {e}")
            return False

    async def add_sub_question(self, sq_id: str, question: str) -> bool:
        """Add a SubQuestion node."""
        if not self.enabled:
            return False
        try:
            await _run_cypher(
                """
                MERGE (q:SubQuestion {id: $id})
                SET q.question = $question, q.updated_at = datetime()
                """,
                {"id": sq_id, "question": question},
            )
            return True
        except Exception as e:
            logger.warning(f"Neo4j: add_sub_question failed: {e}")
            return False

    async def add_related_edges(self) -> int:
        """Auto-create RELATED edges between claims that share ≥1 source."""
        if not self.enabled:
            return 0
        try:
            result = await _run_cypher(
                """
                MATCH (c1:Claim)-[:SUPPORTS]->(s:Source)<-[:SUPPORTS]-(c2:Claim)
                WHERE c1.id < c2.id
                WITH c1, c2, count(s) AS shared
                WHERE shared >= 1
                MERGE (c1)-[r:RELATED]->(c2)
                SET r.shared_sources = shared, r.updated_at = datetime()
                RETURN count(r) AS created
                """,
            )
            return result[0]["created"] if result else 0
        except Exception as e:
            logger.warning(f"Neo4j: add_related_edges failed: {e}")
            return 0

    # ── Query methods ──────────────────────────────────────────────────────

    async def get_claim_sources(self, claim_id: str) -> list[dict]:
        """Get all sources supporting or contradicting a claim."""
        if not self.enabled:
            return []
        try:
            result = await _run_cypher(
                """
                MATCH (c:Claim {id: $claim_id})-[r:SUPPORTS|CONTRADICTS]->(s:Source)
                RETURN s.id AS id, s.url AS url, s.title AS title,
                       s.snippet AS snippet, s.domain_authority AS domain_authority,
                       s.tool_name AS tool_name, type(r) AS relationship,
                       r.weight AS weight
                ORDER BY r.weight DESC
                """,
                {"claim_id": claim_id},
            )
            return result
        except Exception as e:
            logger.warning(f"Neo4j: get_claim_sources failed: {e}")
            return []

    async def get_source_claims(self, source_id: str) -> list[dict]:
        """Get all claims supported by a source (reverse lookup)."""
        if not self.enabled:
            return []
        try:
            result = await _run_cypher(
                """
                MATCH (c:Claim)-[r:SUPPORTS]->(s:Source {id: $source_id})
                RETURN c.id AS id, c.text AS text, c.trust_score AS trust_score,
                       c.trust_label AS trust_label, r.weight AS weight
                ORDER BY r.weight DESC
                """,
                {"source_id": source_id},
            )
            return result
        except Exception as e:
            logger.warning(f"Neo4j: get_source_claims failed: {e}")
            return []

    async def get_related_claims(self, claim_id: str) -> list[dict]:
        """Get claims related to the given claim (share ≥1 source)."""
        if not self.enabled:
            return []
        try:
            result = await _run_cypher(
                """
                MATCH (c1:Claim {id: $claim_id})-[r:RELATED]-(c2:Claim)
                RETURN c2.id AS id, c2.text AS text, c2.trust_score AS trust_score,
                       r.shared_sources AS shared_sources
                ORDER BY r.shared_sources DESC
                """,
                {"claim_id": claim_id},
            )
            return result
        except Exception as e:
            logger.warning(f"Neo4j: get_related_claims failed: {e}")
            return []

    async def get_high_trust_claims(self, min_score: int = 70) -> list[dict]:
        """Get claims with trust_score >= min_score."""
        if not self.enabled:
            return []
        try:
            result = await _run_cypher(
                """
                MATCH (c:Claim)
                WHERE c.trust_score >= $min_score
                RETURN c.id AS id, c.text AS text, c.trust_score AS trust_score,
                       c.trust_label AS trust_label
                ORDER BY c.trust_score DESC
                """,
                {"min_score": min_score},
            )
            return result
        except Exception as e:
            logger.warning(f"Neo4j: get_high_trust_claims failed: {e}")
            return []

    async def get_stats(self) -> dict:
        """Get graph statistics."""
        if not self.enabled:
            return {"enabled": False}
        try:
            result = await _run_cypher(
                """
                MATCH (c:Claim) WITH count(c) AS claims
                MATCH (s:Source) WITH claims, count(s) AS sources
                MATCH (q:SubQuestion) WITH claims, sources, count(q) AS sub_questions
                OPTIONAL MATCH ()-[r:SUPPORTS]-() WITH claims, sources, sub_questions, count(r) AS supports
                OPTIONAL MATCH ()-[r:CONTRADICTS]-() WITH claims, sources, sub_questions, supports, count(r) AS contradicts
                OPTIONAL MATCH ()-[r:RELATED]-() WITH claims, sources, sub_questions, supports, contradicts, count(r) AS related
                RETURN claims, sources, sub_questions, supports, contradicts, related
                """,
            )
            data = result[0] if result else {}
            data["enabled"] = True
            return data
        except Exception as e:
            logger.warning(f"Neo4j: get_stats failed: {e}")
            return {"enabled": False, "error": str(e)}

    async def get_subgraph(self, claim_id: str, depth: int = 2) -> dict:
        """Get a subgraph centered on a claim, up to N hops deep."""
        if not self.enabled:
            return {}
        try:
            result = await _run_cypher(
                """
                MATCH path = (c:Claim {id: $claim_id})-[*1..$depth]-(n)
                WITH nodes(path) AS ns, relationships(path) AS rs
                RETURN [n IN ns | {id: n.id, labels: labels(n), properties: properties(n)}] AS nodes,
                       [r IN rs | {type: type(r), start: startNode(r).id, end: endNode(r).id, properties: properties(r)}] AS edges
                LIMIT 50
                """,
                {"claim_id": claim_id, "depth": depth},
            )
            if result:
                return {"nodes": result[0]["nodes"], "edges": result[0]["edges"]}
            return {"nodes": [], "edges": []}
        except Exception as e:
            logger.warning(f"Neo4j: get_subgraph failed: {e}")
            return {}

    async def export_all(self) -> dict:
        """Export the entire graph as nodes + edges (for API response)."""
        if not self.enabled:
            return {"nodes": [], "edges": [], "stats": {"enabled": False}}
        try:
            nodes_result = await _run_cypher(
                "MATCH (n) RETURN n.id AS id, labels(n) AS labels, properties(n) AS properties"
            )
            edges_result = await _run_cypher(
                "MATCH ()-[r]->() RETURN type(r) AS type, startNode(r).id AS source, endNode(r).id AS target, properties(r) AS properties"
            )
            stats = await self.get_stats()
            return {
                "nodes": [
                    {"id": n["id"], "labels": n["labels"], **n["properties"]}
                    for n in nodes_result
                ],
                "edges": [
                    {"type": e["type"], "source": e["source"], "target": e["target"], **e["properties"]}
                    for e in edges_result
                ],
                "stats": stats,
            }
        except Exception as e:
            logger.warning(f"Neo4j: export_all failed: {e}")
            return {"nodes": [], "edges": [], "stats": {"enabled": False, "error": str(e)}}

    async def clear_graph(self) -> bool:
        """Delete all nodes and edges (use with caution)."""
        if not self.enabled:
            return False
        try:
            await _run_cypher("MATCH (n) DETACH DELETE n")
            return True
        except Exception as e:
            logger.warning(f"Neo4j: clear_graph failed: {e}")
            return False
