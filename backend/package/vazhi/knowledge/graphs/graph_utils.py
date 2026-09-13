import re

from vazhi.storage.neo4j.manager import safe_neo4j_label
from vazhi.utils.hash_utils import hashstr

CYPHER_MERGE_CHUNK = """
MERGE (c:Chunk:VazhiKB:`{db_label}` {{chunk_id: $chunk_id}})
SET c.file_id = $file_id, c.kb_id = $kb_id, c.chunk_index = $chunk_index, c.content_preview = $content_preview
"""

CYPHER_MERGE_ENTITY_MENTION = """
MATCH (c:Chunk:VazhiKB:`{db_label}` {{chunk_id: $chunk_id}})
MERGE (e:Entity:VazhiKB:`{db_label}` {{kb_id: $kb_id, normalized_name: $normalized_name, label: $entity_label}})
SET e.entity_id = $entity_id, e.name = $name
MERGE (c)-[m:MENTIONS {{chunk_id: $chunk_id, file_id: $file_id, kb_id: $kb_id}}]->(e)
"""

CYPHER_MERGE_RELATION = """
MATCH (source:Entity:VazhiKB:`{db_label}` {{kb_id: $kb_id, normalized_name: $source_name, label: $source_label}})
MATCH (target:Entity:VazhiKB:`{db_label}` {{kb_id: $kb_id, normalized_name: $target_name, label: $target_label}})
MERGE (source)-[r:RELATION {{kb_id: $kb_id, chunk_id: $chunk_id, source_name: $source_name, target_name: $target_name, type: $relation_type}}]->(target)
SET r.triple_id = $triple_id, r.text = $text, r.file_id = $file_id
"""


def normalize_entity_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def compute_entity_id(kb_id: str, normalized_name: str, label: str) -> str:
    return hashstr(f"{kb_id}:{normalized_name}:{label}", length=32)


def compute_triple_id(kb_id: str, source_name: str, target_name: str, relation_type: str) -> str:
    return hashstr(f"{kb_id}:{source_name}:{target_name}:{relation_type}", length=32)


def db_label_for(kb_id: str) -> str:
    return safe_neo4j_label(f"kb_{hashstr(kb_id, length=16)}")
