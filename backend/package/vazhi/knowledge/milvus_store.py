import asyncio
import weakref

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

from vazhi.knowledge.chunking.ragflow_like.dispatcher import chunk_markdown
from vazhi.models.embed import get_embedding_model

_CONNECTION_ALIAS = "default"
_COLLECTION_NAME = "vazhi_kb"
_CONTENT_SPARSE_FIELD = "content_sparse"
_CONTENT_ANALYZER_PARAMS = {"type": "english"}
_VECTOR_METRIC_TYPE = "COSINE"

MILVUS_QUERY_OFFLOAD_LIMIT = 8
_milvus_query_offload_semaphore_refs: dict[int, "weakref.ref[asyncio.Semaphore]"] = {}


def _get_milvus_query_offload_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(loop)
    ref = _milvus_query_offload_semaphore_refs.get(key)
    semaphore = ref() if ref is not None else None
    if semaphore is None:
        semaphore = asyncio.Semaphore(MILVUS_QUERY_OFFLOAD_LIMIT)

        def cleanup(_ref, key=key):
            _milvus_query_offload_semaphore_refs.pop(key, None)

        _milvus_query_offload_semaphore_refs[key] = weakref.ref(semaphore, cleanup)
    return semaphore


async def _run_milvus_query_io(func, /, *args, **kwargs):
    semaphore = _get_milvus_query_offload_semaphore()
    await semaphore.acquire()
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))

    def release_capacity(completed_task: asyncio.Task):
        semaphore.release()
        if completed_task.cancelled():
            return
        completed_task.exception()

    task.add_done_callback(release_capacity)
    return await asyncio.shield(task)


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
            FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=100),
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
        collection.create_index("kb_id", {"index_type": "INVERTED"})
    collection.load()
    return collection


async def add_document(
    kb_id: str,
    doc_id: str,
    content: str,
    filename: str = "document.md",
    preset_id: str = "general",
    parser_config: dict | None = None,
) -> None:
    records = chunk_markdown(
        content,
        file_id=doc_id,
        filename=filename,
        processing_params={"chunk_preset_id": preset_id, "chunk_parser_config": parser_config or {}},
    )
    if not records:
        return

    embed_model = get_embedding_model()
    ids = [r["id"] for r in records]
    kb_ids = [kb_id for _ in records]
    contents = [r["content"] for r in records]
    vectors = await asyncio.to_thread(embed_model.encode, contents)

    collection = await asyncio.to_thread(get_or_create_collection)
    await asyncio.to_thread(collection.insert, [ids, kb_ids, contents, vectors])
    await asyncio.to_thread(collection.flush)


async def search(kb_id: str, query_text: str, top_k: int = 3, mode: str = "hybrid") -> list[dict]:
    collection = await _run_milvus_query_io(get_or_create_collection)
    kb_expr = f'kb_id == "{kb_id}"'

    if mode == "vector":
        embed_model = get_embedding_model()
        query_vector = (await _run_milvus_query_io(embed_model.encode, query_text))[0]
        results = await _run_milvus_query_io(
            collection.search,
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": _VECTOR_METRIC_TYPE, "params": {"nprobe": 10}},
            limit=top_k,
            expr=kb_expr,
            output_fields=["content"],
        )
        return [{"content": hit.entity.get("content"), "score": hit.distance} for hit in results[0]]

    if mode == "keyword":
        results = await _run_milvus_query_io(
            collection.search,
            data=[query_text],
            anns_field=_CONTENT_SPARSE_FIELD,
            param={"metric_type": "BM25", "params": {"drop_ratio_search": 0.2}},
            limit=top_k,
            expr=kb_expr,
            output_fields=["content"],
        )
        return [{"content": hit.entity.get("content"), "score": hit.distance} for hit in results[0]]

    embed_model = get_embedding_model()
    query_vector = (await _run_milvus_query_io(embed_model.encode, query_text))[0]
    vector_request = AnnSearchRequest(
        data=[query_vector],
        anns_field="embedding",
        param={"metric_type": _VECTOR_METRIC_TYPE, "params": {"nprobe": 10}},
        limit=top_k,
        expr=kb_expr,
    )
    bm25_request = AnnSearchRequest(
        data=[query_text],
        anns_field=_CONTENT_SPARSE_FIELD,
        param={"metric_type": "BM25", "params": {"drop_ratio_search": 0.2}},
        limit=top_k,
        expr=kb_expr,
    )
    results = await _run_milvus_query_io(
        collection.hybrid_search,
        reqs=[vector_request, bm25_request],
        rerank=WeightedRanker(0.7, 0.3),
        limit=top_k,
        output_fields=["content"],
    )
    return [{"content": hit.entity.get("content"), "score": hit.distance} for hit in results[0]]
