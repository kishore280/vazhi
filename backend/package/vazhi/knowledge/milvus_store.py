from pymilvus import (
    AnnSearchRequest,
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    WeightedRanker,
    connections,
    utility,
)

from vazhi.models.embed import get_embedding_model

_CONNECTION_ALIAS = "default"
_COLLECTION_NAME = "vazhi_kb"
_CONTENT_SPARSE_FIELD = "content_sparse"
_CONTENT_ANALYZER_PARAMS = {"type": "english"}
_VECTOR_METRIC_TYPE = "COSINE"


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
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params=_CONTENT_ANALYZER_PARAMS,
            ),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embed_model.dimension),
            FieldSchema(name=_CONTENT_SPARSE_FIELD, dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]
        bm25_function = Function(
            name="content_bm25",
            input_field_names=["content"],
            output_field_names=[_CONTENT_SPARSE_FIELD],
            function_type=FunctionType.BM25,
        )
        schema = CollectionSchema(fields=fields, description="vazhi knowledge base", functions=[bm25_function])
        collection = Collection(name=_COLLECTION_NAME, schema=schema, using=_CONNECTION_ALIAS)
        collection.create_index(
            "embedding",
            {"metric_type": _VECTOR_METRIC_TYPE, "index_type": "IVF_FLAT", "params": {"nlist": 1024}},
        )
        collection.create_index(
            _CONTENT_SPARSE_FIELD,
            {
                "metric_type": "BM25",
                "index_type": "SPARSE_INVERTED_INDEX",
                "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
            },
        )
    collection.load()
    return collection


def add_document(doc_id: str, content: str) -> None:
    embed_model = get_embedding_model()
    vector = embed_model.encode(content)[0]
    collection = get_or_create_collection()
    collection.insert([[doc_id], [content], [vector]])
    collection.flush()


def search(query_text: str, top_k: int = 3, mode: str = "hybrid") -> list[dict]:
    collection = get_or_create_collection()

    if mode == "vector":
        embed_model = get_embedding_model()
        query_vector = embed_model.encode(query_text)[0]
        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": _VECTOR_METRIC_TYPE, "params": {"nprobe": 10}},
            limit=top_k,
            output_fields=["content"],
        )
        return [{"content": hit.entity.get("content"), "score": hit.distance} for hit in results[0]]

    if mode == "keyword":
        results = collection.search(
            data=[query_text],
            anns_field=_CONTENT_SPARSE_FIELD,
            param={"metric_type": "BM25", "params": {"drop_ratio_search": 0.2}},
            limit=top_k,
            output_fields=["content"],
        )
        return [{"content": hit.entity.get("content"), "score": hit.distance} for hit in results[0]]

    embed_model = get_embedding_model()
    query_vector = embed_model.encode(query_text)[0]
    vector_request = AnnSearchRequest(
        data=[query_vector],
        anns_field="embedding",
        param={"metric_type": _VECTOR_METRIC_TYPE, "params": {"nprobe": 10}},
        limit=top_k,
    )
    bm25_request = AnnSearchRequest(
        data=[query_text],
        anns_field=_CONTENT_SPARSE_FIELD,
        param={"metric_type": "BM25", "params": {"drop_ratio_search": 0.2}},
        limit=top_k,
    )
    results = collection.hybrid_search(
        reqs=[vector_request, bm25_request],
        rerank=WeightedRanker(0.7, 0.3),
        limit=top_k,
        output_fields=["content"],
    )
    return [{"content": hit.entity.get("content"), "score": hit.distance} for hit in results[0]]
