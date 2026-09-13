import asyncio

from vazhi.knowledge.graphs.extractors.llm import extract_triples
from vazhi.knowledge.graphs.graph_utils import (
    CYPHER_MERGE_CHUNK,
    CYPHER_MERGE_ENTITY_MENTION,
    CYPHER_MERGE_RELATION,
    compute_entity_id,
    compute_triple_id,
    db_label_for,
    normalize_entity_name,
)
from vazhi.storage.neo4j.manager import get_shared_neo4j_connection


def _write_chunk_and_triples(
    driver, kb_id: str, chunk_id: str, file_id: str, chunk_index: int, content: str, relations: list[dict]
) -> None:
    db_label = db_label_for(kb_id)

    with driver.session() as session:
        session.run(
            CYPHER_MERGE_CHUNK.format(db_label=db_label),
            chunk_id=chunk_id,
            file_id=file_id,
            kb_id=kb_id,
            chunk_index=chunk_index,
            content_preview=content[:200],
        )

        for relation in relations:
            source = relation.get("source") or {}
            target = relation.get("target") or {}
            source_name = normalize_entity_name(source.get("text", ""))
            target_name = normalize_entity_name(target.get("text", ""))
            source_label = source.get("label") or "Entity"
            target_label = target.get("label") or "Entity"
            relation_type = relation.get("label") or "RELATED_TO"

            if not source_name or not target_name:
                continue

            session.run(
                CYPHER_MERGE_ENTITY_MENTION.format(db_label=db_label),
                chunk_id=chunk_id,
                file_id=file_id,
                kb_id=kb_id,
                normalized_name=source_name,
                entity_label=source_label,
                entity_id=compute_entity_id(kb_id, source_name, source_label),
                name=source.get("text", ""),
            )
            session.run(
                CYPHER_MERGE_ENTITY_MENTION.format(db_label=db_label),
                chunk_id=chunk_id,
                file_id=file_id,
                kb_id=kb_id,
                normalized_name=target_name,
                entity_label=target_label,
                entity_id=compute_entity_id(kb_id, target_name, target_label),
                name=target.get("text", ""),
            )
            session.run(
                CYPHER_MERGE_RELATION.format(db_label=db_label),
                kb_id=kb_id,
                chunk_id=chunk_id,
                file_id=file_id,
                source_name=source_name,
                target_name=target_name,
                source_label=source_label,
                target_label=target_label,
                relation_type=relation_type,
                triple_id=compute_triple_id(kb_id, source_name, target_name, relation_type),
                text=relation.get("text", ""),
            )


async def index_chunk_into_graph(kb_id: str, chunk_id: str, file_id: str, chunk_index: int, content: str) -> int:
    relations = await extract_triples(content)
    conn = get_shared_neo4j_connection()
    await asyncio.to_thread(
        _write_chunk_and_triples, conn.driver, kb_id, chunk_id, file_id, chunk_index, content, relations
    )
    return len(relations)
