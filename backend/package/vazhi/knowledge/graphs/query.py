import asyncio

from vazhi.knowledge.graphs.graph_utils import db_label_for
from vazhi.storage.neo4j.manager import get_shared_neo4j_connection, neo4j_read

CYPHER_FETCH_ENTITIES = """
MATCH (e:Entity:VazhiKB:`{db_label}` {{kb_id: $kb_id}})
RETURN e.entity_id AS id, e.name AS name, e.label AS type
LIMIT $max_nodes
"""

CYPHER_FETCH_RELATIONS = """
MATCH (s:Entity:VazhiKB:`{db_label}` {{kb_id: $kb_id}})-[r:RELATION]->(t:Entity:VazhiKB:`{db_label}` {{kb_id: $kb_id}})
RETURN r.triple_id AS id, s.entity_id AS source_id, t.entity_id AS target_id, r.type AS type
LIMIT $max_edges
"""


def _fetch_subgraph(kb_id: str, max_nodes: int) -> dict:
    conn = get_shared_neo4j_connection()
    db_label = db_label_for(kb_id)

    node_rows = neo4j_read(
        conn.driver, CYPHER_FETCH_ENTITIES.format(db_label=db_label), kb_id=kb_id, max_nodes=max_nodes
    )
    node_ids = {row["id"] for row in node_rows}

    edge_rows = neo4j_read(
        conn.driver, CYPHER_FETCH_RELATIONS.format(db_label=db_label), kb_id=kb_id, max_edges=max_nodes * 5
    )
    edges = [row for row in edge_rows if row["source_id"] in node_ids and row["target_id"] in node_ids]

    return {"nodes": node_rows, "edges": edges}


async def get_subgraph(kb_id: str, max_nodes: int = 200) -> dict:
    return await asyncio.to_thread(_fetch_subgraph, kb_id, max_nodes)
