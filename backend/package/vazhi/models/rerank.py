import httpx


class BaseReranker:
    def __init__(self, base_url: str):
        self.base_url = base_url

    async def acompute_score(self, sentence_pairs: list) -> list[float]:
        raise NotImplementedError


class TEIReranker(BaseReranker):
    async def acompute_score(self, sentence_pairs: list) -> list[float]:
        query, documents = sentence_pairs[0], sentence_pairs[1]
        documents = [documents] if isinstance(documents, str) else list(documents)
        if not documents:
            return []

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url, json={"query": query, "texts": documents}, timeout=30
            )
            response.raise_for_status()
            result = response.json()

        scores_by_index = {item["index"]: item["score"] for item in result}
        return [scores_by_index[i] for i in range(len(documents))]


def get_reranker() -> TEIReranker:
    from vazhi.config import settings

    return TEIReranker(base_url=settings.rerank_base_url)
