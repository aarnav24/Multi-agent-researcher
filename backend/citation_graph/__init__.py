"""Layer C — Citation Graph.

Directed graph of claims → sources → URLs, stored in Neo4j.
Built incrementally as verified claims arrive from the fact-checker.

Schema:
  Nodes:
    :Claim           {id, text, trust_score, trust_label, fact_check_passed, sub_question_id}
    :Source          {id, url, title, snippet, domain_authority, tool_name, published_date}
    :SubQuestion     {id, question}

  Edges:
    [:SUPPORTS]      (Claim → Source, weight=trust_score, supports=True)
    [:CONTRADICTS]   (Claim → Source, weight=trust_score, supports=False)
    [:ANSWERS]       (Claim → SubQuestion)
    [:RELATED]       (Claim → Claim)   # shares ≥1 source
"""

from backend.citation_graph.neo4j_adapter import Neo4jAdapter
from backend.citation_graph.graph import CitationGraph

__all__ = ["CitationGraph", "Neo4jAdapter"]
