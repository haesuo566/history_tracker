from google import genai
from google.genai import types
from loguru import logger

from backend.core.config import settings

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 목록을 gemini-embedding-001로 임베딩해 벡터 목록을 반환한다."""
    if not texts:
        return []

    logger.debug("embedding {} text(s) via {}", len(texts), settings.embedding_model)
    response = _get_client().models.embed_content(
        model=settings.embedding_model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=settings.embedding_dim,
        ),
    )
    return [embedding.values for embedding in response.embeddings]


def embed_query(text: str) -> list[float]:
    """검색 질의문을 gemini-embedding-001로 임베딩해 벡터를 반환한다."""
    response = _get_client().models.embed_content(
        model=settings.embedding_model,
        contents=text,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=settings.embedding_dim,
        ),
    )
    return response.embeddings[0].values
