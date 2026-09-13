import asyncio

import networkx as nx

from vazhi.knowledge.graphs.graph_utils import db_label_for, normalize_entity_name
from vazhi.storage.neo4j.manager import get_shared_neo4j_connection, neo4j_read

CYPHER_FETCH_SUBGRAPH = """
MATCH (n:VazhiKB:`{db_label}` {{kb_id: $kb_id}})
OPTIONAL MATCH (n)-[rel:MENTIONS|RELATION]-(m:VazhiKB:`{db_label}` {{kb_id: $kb_id}})
RETURN
  labels(n) AS n_labels, coalesce(n.chunk_id, n.entity_id) AS n_id,
  labels(m) AS m_labels, coalesce(m.chunk_id, m.entity_id) AS m_id,
  type(rel) AS rel_type
"""


def _find_seed_entities(kb_id: str, query_text: str) -> dict[str, float]:
    conn = get_shared_neo4j_connection()
    db_label = db_label_for(kb_id)
    rows = neo4j_read(
        conn.driver,
        f"MATCH (e:Entity:VazhiKB:`{db_label}` {{kb_id: $kb_id}}) RETURN e.entity_id AS entity_id, e.normalized_name AS normalized_name",
        kb_id=kb_id,
    )
    query_lower = normalize_entity_name(query_text)
    return {row["entity_id"]: 1.0 for row in rows if row["normalized_name"] and row["normalized_name"] in query_lower}


def _fetch_subgraph(kb_id: str) -> nx.Graph:
    conn = get_shared_neo4j_connection()
    db_label = db_label_for(kb_id)
    rows = neo4j_read(conn.driver, CYPHER_FETCH_SUBGRAPH.format(db_label=db_label), kb_id=kb_id)

    graph = nx.Graph()
    node_types: dict[str, str] = {}
    for row in rows:
        if row["n_id"]:
            graph.add_node(row["n_id"])
            node_types[row["n_id"]] = "Chunk" if "Chunk" in (row["n_labels"] or []) else "Entity"
        if row["m_id"] and row["rel_type"]:
            graph.add_node(row["m_id"])
            node_types[row["m_id"]] = "Chunk" if "Chunk" in (row["m_labels"] or []) else "Entity"
            graph.add_edge(row["n_id"], row["m_id"])

    nx.set_node_attributes(graph, node_types, "node_type")
    return graph


def _rank_chunks_by_ppr(kb_id: str, query_text: str, top_k: int) -> list[tuple[str, float]]:
    seed_weights = _find_seed_entities(kb_id, query_text)
    if not seed_weights:
        return []

    graph = _fetch_subgraph(kb_id)
    if graph.number_of_nodes() == 0:
        return []

    total_weight = sum(seed_weights.values())
    personalization = {node: seed_weights.get(node, 0.0) / total_weight for node in graph.nodes}

    scores = nx.pagerank(graph, alpha=0.85, personalization=personalization)

    chunk_scores = [
        (node, score) for node, score in scores.items() if graph.nodes[node].get("node_type") == "Chunk"
    ]
    chunk_scores.sort(key=lambda item: item[1], reverse=True)
    return chunk_scores[:top_k]


async def query_graph(kb_id: str, query_text: str, top_k: int = 5) -> list[dict]:
    ranked = await asyncio.to_thread(_rank_chunks_by_ppr, kb_id, query_text, top_k)
    return [{"chunk_id": chunk_id, "score": score} for chunk_id, score in ranked]
