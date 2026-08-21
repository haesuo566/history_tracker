"""색인·검색에 쓰는 임베딩. 어느 제공자를 쓰는지는 설정이 정한다.

이 모듈 밖(services.indexing, services.search)은 embed_texts / embed_query 두 함수만 알고,
제공자가 Gemini인지 TEI인지는 모른다.
"""

from google.genai import types
from loguru import logger

from backend.core.config import settings
from backend.core.model_catalog import (
    FALLBACK_MAX_INPUT_TOKENS,
    EmbeddingProvider,
    chunk_chars_for,
    find_embedding_model,
)
from backend.services import tei
from backend.services.gemini import get_client
from backend.services.runtime_settings import RuntimeSettings, get_settings

# 차원을 알아내려고 보내는 문장. 내용은 상관없지만 빈 문자열은 모델이 거부할 수 있다.
_PROBE_TEXT = "차원 확인"


def embed_texts(texts: list[str]) -> list[list[float]]:
    """색인할 텍스트 목록을 임베딩해 입력과 같은 순서로 벡터를 돌려준다."""
    if not texts:
        return []

    current = get_settings()
    if current.embedding_provider is EmbeddingProvider.TEI:
        return tei.embed(texts, base_url=current.tei_base_url, model=current.tei_model or None)

    logger.debug("embedding {} text(s) via {}", len(texts), current.embedding_model)
    response = get_client().models.embed_content(
        model=current.embedding_model,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=settings.embedding_dim,
        ),
    )
    return [embedding.values for embedding in response.embeddings]


def embed_query(text: str) -> list[float]:
    """검색 질의문을 임베딩해 벡터를 돌려준다.

    Gemini는 문서와 질의를 다른 task_type으로 임베딩한다. TEI에는 그런 구분이 없어 문서와 같은
    방식으로 보낸다(services.tei 주석 참고).
    """
    current = get_settings()
    if current.embedding_provider is EmbeddingProvider.TEI:
        vectors = tei.embed([text], base_url=current.tei_base_url, model=current.tei_model or None)
        return vectors[0]

    response = get_client().models.embed_content(
        model=current.embedding_model,
        contents=text,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=settings.embedding_dim,
        ),
    )
    return response.embeddings[0].values


def detect_dim(current: RuntimeSettings | None = None) -> int:
    """지금 설정된 제공자가 실제로 내놓는 벡터 차원을 한 번 호출해서 알아낸다.

    사용자에게 차원을 입력받지 않는 것은, 틀리게 적으면 vec_chunks를 그 차원으로 만들어 두고
    색인이 전부 실패하기 때문이다. 모델이 몇 차원을 내는지는 모델만 안다.
    """
    current = current or get_settings()
    if current.embedding_provider is EmbeddingProvider.TEI:
        vectors = tei.embed([_PROBE_TEXT], base_url=current.tei_base_url, model=current.tei_model or None)
        return len(vectors[0])

    # Gemini는 output_dimensionality로 우리가 차원을 지정하므로 물어볼 것이 없다.
    return settings.embedding_dim


def detect_chunk_chars(current: RuntimeSettings | None = None) -> int:
    """지금 설정된 임베딩이 한 번에 받는 분량을 청크 문자 수로 환산한다.

    입력 한계는 모델이 정하고 우리가 고를 수 있는 값이 아니다. 그래서 설정으로 받지 않고 여기서
    알아낸다 — 넘겨서 보내면 Gemini도 TEI도 오류 없이 뒷부분을 버리므로, 사람이 숫자를 적어 넣는
    방식은 조용한 품질 손실로 되돌아온다.
    """
    current = current or get_settings()

    if current.embedding_provider is EmbeddingProvider.TEI:
        tokens = tei.fetch_max_input_tokens(current.tei_base_url) or FALLBACK_MAX_INPUT_TOKENS
    else:
        option = find_embedding_model(current.embedding_model)
        # 목록 밖 모델(.env로 지정)은 한계를 알 수 없다. 짧게 잡아 잘리지 않는 쪽을 택한다.
        tokens = option.max_input_tokens if option is not None else FALLBACK_MAX_INPUT_TOKENS

    return chunk_chars_for(tokens)
