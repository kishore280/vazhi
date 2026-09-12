from abc import ABC, abstractmethod

import httpx
import requests


class BaseEmbeddingModel(ABC):
    def __init__(self, model: str, base_url: str, api_key: str, dimension: int):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.dimension = dimension

    @abstractmethod
    def encode(self, message: list[str] | str) -> list[list[float]]:
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    async def aencode(self, message: list[str] | str) -> list[list[float]]:
        raise NotImplementedError("Subclasses must implement this method")


class OtherEmbedding(BaseEmbeddingModel):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def build_payload(self, message: list[str] | str) -> dict:
        return {"model": self.model, "input": message}

    def encode(self, message: list[str] | str) -> list[list[float]]:
        payload = self.build_payload(message)
        response = requests.post(self.base_url, json=payload, headers=self.headers, timeout=60)
        response.raise_for_status()
        return self._extract_embeddings(response.json())

    async def aencode(self, message: list[str] | str) -> list[list[float]]:
        payload = self.build_payload(message)
        async with httpx.AsyncClient() as client:
            response = await client.post(self.base_url, json=payload, headers=self.headers, timeout=60)
            response.raise_for_status()
            return self._extract_embeddings(response.json())

    @staticmethod
    def _extract_embeddings(result: dict) -> list[list[float]]:
        if not isinstance(result, dict) or "data" not in result:
            raise ValueError(f"Embedding failed: Invalid response format {result}")
        return [item["embedding"] for item in result["data"]]


def get_embedding_model() -> OtherEmbedding:
    from vazhi.config import settings

    return OtherEmbedding(
        model=settings.embed_model,
        base_url=settings.embed_base_url,
        api_key=settings.embed_api_key,
        dimension=settings.embed_dimension,
    )
