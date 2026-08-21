from pydantic import BaseModel, field_validator

from backend.core.config import settings
from backend.core.model_catalog import (
    EmbeddingProvider,
    find_embedding_model,
    find_generation_model,
)


class ModelOption(BaseModel):
    """설정 화면의 선택지 한 줄."""

    id: str
    label: str


class ProviderOption(BaseModel):
    """임베딩 제공자 선택지 한 줄."""

    id: str
    label: str


class SettingsResponse(BaseModel):
    """GET·PATCH /settings 응답. 지금 유효한 값과 고를 수 있는 선택지를 함께 담는다.

    API key 원문은 담지 않는다. 저장된 값을 화면에 되돌려줄 이유가 없고, 되돌려주면 설정 화면을
    여는 것만으로 키가 응답 본문·브라우저 캐시·서버 로그를 타고 흐른다. 대신 입력된 키가 내가 넣은
    그것인지 알아볼 수 있도록 끝 네 자리만 남긴 힌트를 준다.
    """

    answer_model: str
    query_rewrite_model: str
    embedding_model: str
    embedding_provider: EmbeddingProvider
    tei_base_url: str
    tei_model: str
    # Gemini 경로에서 요청하는 차원(.env 고정). TEI 경로에서는 쓰이지 않는다 — 그쪽 차원은
    # 서버에 올라간 모델이 정한다.
    embedding_dim: int
    # 지금 색인에 들어 있는 벡터의 차원. 위 값과 다를 수 있다(TEI로 재색인한 경우).
    indexed_dim: int
    # 지금 색인의 청크가 몇 글자로 잘려 있는지.
    indexed_chunk_chars: int
    # 지금 설정대로 색인하면 쓰게 될 청크 크기. TEI는 서버에 물어야 알 수 있어 None이다.
    expected_chunk_chars: int | None = None
    # 색인을 다시 만들어야 지금 설정대로 동작하면 True.
    reindex_required: bool
    # 벡터 검색이 지금 동작하는지. False면 본문 단어 검색만으로 답하고 있다.
    vector_search_active: bool
    api_key_configured: bool
    api_key_hint: str | None = None
    embedding_providers: list[ProviderOption]
    generation_models: list[ModelOption]
    embedding_models: list[ModelOption]


class SettingsUpdateRequest(BaseModel):
    """PATCH /settings 요청 본문. 넘긴 항목만 바꾸고, 생략하거나 null인 항목은 그대로 둔다.

    부분 갱신인 것은 API key 때문이다. 화면은 저장된 키 원문을 모르므로 모델만 바꾸는 저장에서
    키를 함께 보낼 수가 없다. 빈 문자열은 '지우기'가 아니라 오류로 본다 — 키 없이는 어떤 질의도
    처리할 수 없어, 저장 버튼을 잘못 눌러 앱이 멈추는 쪽이 손해가 크다.
    """

    answer_model: str | None = None
    query_rewrite_model: str | None = None
    embedding_model: str | None = None
    embedding_provider: EmbeddingProvider | None = None
    tei_base_url: str | None = None
    tei_model: str | None = None
    gemini_api_key: str | None = None

    @field_validator("tei_base_url")
    @classmethod
    def _clean_base_url(cls, value: str | None) -> str | None:
        """TEI 주소는 http(s) 절대 주소여야 한다. 형태만 보고, 실제로 붙는지는 재색인이 확인한다."""
        if value is None:
            return None
        stripped = value.strip().rstrip("/")
        if not stripped:
            raise ValueError("tei_base_url must not be blank")
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("tei_base_url must start with http:// or https://")
        return stripped

    @field_validator("tei_model")
    @classmethod
    def _clean_tei_model(cls, value: str | None) -> str | None:
        # TEI는 서버에 올린 모델을 쓰므로 모델명은 표시·호환 서버용이고 비워 둘 수 있다.
        return None if value is None else value.strip()

    @field_validator("answer_model", "query_rewrite_model")
    @classmethod
    def _known_generation_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if find_generation_model(value) is None:
            raise ValueError(f"unknown generation model: {value}")
        return value

    @field_validator("embedding_model")
    @classmethod
    def _known_embedding_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        option = find_embedding_model(value)
        if option is None:
            raise ValueError(f"unknown embedding model: {value}")
        # 차원을 못 내는 모델로 바꾸면 저장은 되고 색인만 전부 실패한다. 그 전에 막는다.
        if option.max_dim < settings.embedding_dim:
            raise ValueError(
                f"{value} supports up to {option.max_dim} dimensions "
                f"but EMBEDDING_DIM is {settings.embedding_dim}"
            )
        return value

    @field_validator("gemini_api_key")
    @classmethod
    def _clean_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("gemini_api_key must not be blank")
        return stripped
