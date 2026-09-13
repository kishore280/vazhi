from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from vazhi.models.embed import get_embedding_model

_CONNECTION_ALIAS = "default"
_COLLECTION_NAME = "vazhi_kb_entities"
_VECTOR_METRIC_TYPE = "COSINE"


def _connect() -> None:
    from vazhi.config import settings

    connections.connect(alias=_CONNECTION_ALIAS, uri=settings.milvus_uri, token=settings.milvus_token)


def get_or_create_entity_collection() -> Collection:
    _connect()
    if utility.has_collection(_COLLECTION_NAME, using=_CONNECTION_ALIAS):
        collection = Collection(name=_COLLECTION_NAME, using=_CONNECTION_ALIAS)
    else:
        embed_model = get_embedding_model()
        fields = [
            FieldSchema(name="entity_id", dtype=DataType.VARCHAR, max_length=100, is_primary=True),
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=1000),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embed_model.dimension),
        ]
        schema = CollectionSchema(fields=fields, description="vazhi graph entities")
        collection = Collection(name=_COLLECTION_NAME, schema=schema, using=_CONNECTION_ALIAS)
        collection.create_index(
            "embedding",
            {"metric_type": _VECTOR_METRIC_TYPE, "index_type": "IVF_FLAT", "params": {"nlist": 1024}},
        )
        collection.create_index("kb_id", {"index_type": "INVERTED"})
    collection.load()
    return collection


def add_entity(kb_id: str, entity_id: str, name: str) -> None:
    embed_model = get_embedding_model()
    vector = embed_model.encode(name)[0]
    collection = get_or_create_entity_collection()
    collection.upsert([[entity_id], [kb_id], [name], [vector]])


def search_entities(kb_id: str, query_text: str, top_k: int = 5) -> dict[str, float]:
    embed_model = get_embedding_model()
    query_vector = embed_model.encode(query_text)[0]
    collection = get_or_create_entity_collection()
    results = collection.search(
        data=[query_vector],
        anns_field="embedding",
        param={"metric_type": _VECTOR_METRIC_TYPE, "params": {"nprobe": 10}},
        limit=top_k,
        expr=f'kb_id == "{kb_id}"',
    )
    return {hit.id: hit.distance for hit in results[0]}
