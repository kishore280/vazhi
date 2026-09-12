from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from vazhi.models.embed import get_embedding_model

_CONNECTION_ALIAS = "default"
_COLLECTION_NAME = "vazhi_kb"


def _connect() -> None:
    from vazhi.config import settings

    connections.connect(alias=_CONNECTION_ALIAS, uri=settings.milvus_uri, token=settings.milvus_token)


def get_or_create_collection() -> Collection:
    _connect()
    if utility.has_collection(_COLLECTION_NAME, using=_CONNECTION_ALIAS):
        collection = Collection(name=_COLLECTION_NAME, using=_CONNECTION_ALIAS)
    else:
        embed_model = get_embedding_model()
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=100, is_primary=True),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embed_model.dimension),
        ]
        schema = CollectionSchema(fields=fields, description="vazhi knowledge base")
        collection = Collection(name=_COLLECTION_NAME, schema=schema, using=_CONNECTION_ALIAS)
        collection.create_index(
            "embedding",
            {"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 1024}},
        )
    collection.load()
    return collection


def add_document(doc_id: str, content: str) -> None:
    embed_model = get_embedding_model()
    vector = embed_model.encode(content)[0]
    collection = get_or_create_collection()
    collection.insert([[doc_id], [content], [vector]])
    collection.flush()


def search(query_text: str, top_k: int = 3) -> list[dict]:
    embed_model = get_embedding_model()
    query_vector = embed_model.encode(query_text)[0]
    collection = get_or_create_collection()
    results = collection.search(
        data=[query_vector],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 10}},
        limit=top_k,
        output_fields=["content"],
    )
    return [{"content": hit.entity.get("content"), "score": hit.distance} for hit in results[0]]
