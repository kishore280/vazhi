import sys

sys.path.insert(0, "package")

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections

from vazhi.models.embed import get_embedding_model

connections.connect(alias="default", uri="http://milvus:19530", token="")

embed_model = get_embedding_model()

collection_name = "test_kb"

fields = [
    FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=100, is_primary=True),
    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embed_model.dimension),
]
schema = CollectionSchema(fields=fields, description="test collection")
collection = Collection(name=collection_name, schema=schema, using="default")

index_params = {"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 1024}}
collection.create_index("embedding", index_params)
collection.load()

docs = [
    ("1", "The capital of France is Paris."),
    ("2", "Bananas are a good source of potassium."),
    ("3", "The Eiffel Tower is located in Paris."),
]
for doc_id, content in docs:
    vector = embed_model.encode(content)[0]
    collection.insert([[doc_id], [content], [vector]])

collection.flush()

query = "What city is the Eiffel Tower in?"
query_vector = embed_model.encode(query)[0]
search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
results = collection.search(
    data=[query_vector],
    anns_field="embedding",
    param=search_params,
    limit=3,
    output_fields=["content"],
)

print(f"Query: {query}")
for hit in results[0]:
    print(f"  score={hit.distance:.4f}  {hit.entity.get('content')}")

collection.release()
