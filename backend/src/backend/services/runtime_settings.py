"""운영 중에 바꿀 수 있는 설정을 DB에서 읽고 쓴다.

core.config.Settings는 .env를 기동 시점에 한 번 읽으므로 화면에서 바꿀 수 없다. 여기서는 그중
설정 화면이 다루는 항목(API key, 모델 3종)만 app_settings 테이블에 덮어써서 재기동 없이 바꾼다.
DB에 값이 없는 항목은 .env 값을 그대로 쓴다 — 설정 화면을 한 번도 쓰지 않은 환경의 동작이
기존과 같아야 한다.
"""

from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.model_catalog import (
    DEFAULT_EMBEDDING_PROVIDER,
    EMBEDDING_MODELS,
    FALLBACK_MAX_INPUT_TOKENS,
    GENERATION_MODELS,
    PROVIDER_LABELS,
    EmbeddingProvider,
    chunk_chars_for,
    find_embedding_model,
)
from backend.db.session import SessionLocal
from backend.models.app_setting import AppSetting
from backend.schemas.settings import ModelOption, ProviderOption, SettingsResponse

API_KEY = "gemini_api_key"
EMBEDDING_MODEL = "embedding_model"
QUERY_REWRITE_MODEL = "query_rewrite_model"
ANSWER_MODEL = "answer_model"
EMBEDDING_PROVIDER = "embedding_provider"
TEI_BASE_URL = "tei_base_url"
TEI_MODEL = "tei_model"

SETTING_KEYS = frozenset(
    {API_KEY, EMBEDDING_MODEL, QUERY_REWRITE_MODEL, ANSWER_MODEL, EMBEDDING_PROVIDER, TEI_BASE_URL, TEI_MODEL}
)

# 색인이 어떤 임베딩으로 만들어졌는지 남겨 두는 자리. 설정이 아니라 상태이므로 설정 화면이
# 직접 쓰지 않고 재색인(services.reindex)만 갱신한다.
INDEXED_DIM = "indexed_embedding_dim"
INDEXED_SIGNATURE = "indexed_embedding_signature"
INDEXED_CHUNK_CHARS = "indexed_chunk_chars"

INDEX_STATE_KEYS = frozenset({INDEXED_DIM, INDEXED_SIGNATURE, INDEXED_CHUNK_CHARS})

# 청크 크기를 기록하기 전에 만들어진 색인은 이 값으로 쌓여 있다(옛 상수 2048토큰 x 4자).
LEGACY_CHUNK_CHARS = 8192


class RuntimeSettings(BaseModel):
    """지금 유효한 설정값. DB에 저장된 값과 .env 폴백을 합친 결과다."""

    gemini_api_key: str
    embedding_model: str
    query_rewrite_model: str
    answer_model: str
    # provider와 TEI 주소는 .env에 두지 않는다. Settings는 항목이 비면 기동에 실패하므로,
    # 필수 항목을 새로 더하면 이미 돌고 있는 배포가 .env를 고칠 때까지 뜨지 않는다.
    embedding_provider: EmbeddingProvider
    tei_base_url: str
    tei_model: str
    # 지금 색인에 들어 있는 벡터의 차원과, 그것을 만든 임베딩의 서명.
    indexed_dim: int
    indexed_signature: str
    # 지금 색인의 청크가 몇 글자로 잘려 있는지. 색인 배치가 이 값으로 자른다.
    indexed_chunk_chars: int

    @property
    def embedding_signature(self) -> str:
        """지금 설정이 만들어 낼 벡터의 출처. 색인에 남은 서명과 비교해 재색인 필요를 판단한다."""
        if self.embedding_provider is EmbeddingProvider.TEI:
            # TEI는 서버에 올린 모델 하나를 쓴다. 모델명을 적지 않았으면 주소가 그 자리를 대신한다.
            return f"{EmbeddingProvider.TEI.value}:{self.tei_model or self.tei_base_url}"
        return f"{EmbeddingProvider.GEMINI.value}:{self.embedding_model}"

    @property
    def vector_index_usable(self) -> bool:
        """색인의 벡터를 지금 질의 벡터와 견줄 수 있으면 True.

        서명이 같으면 같은 모델이 만든 같은 공간의 좌표다. 청크 경계가 달라도 좌표끼리는 견줄 수
        있으므로 이 판단에는 넣지 않는다 — 그 경우는 검색이 되긴 하되 촘촘함이 예전 기준일 뿐이다.
        """
        return self.indexed_signature == self.embedding_signature

    @property
    def expected_chunk_chars(self) -> int | None:
        """서버에 묻지 않고 알 수 있는 청크 크기. TEI는 /info를 봐야 하므로 None.

        Gemini는 모델별 입력 한계가 상수로 있어 즉시 환산된다. TEI는 서명이 같으면 같은 서버·같은
        모델이라 청크 크기도 그대로이므로, 굳이 물어서 확인할 이유가 없다.
        """
        if self.embedding_provider is EmbeddingProvider.TEI:
            return None
        option = find_embedding_model(self.embedding_model)
        tokens = option.max_input_tokens if option is not None else FALLBACK_MAX_INPUT_TOKENS
        return chunk_chars_for(tokens)

    @property
    def reindex_required(self) -> bool:
        """색인을 다시 만들어야 지금 설정대로 동작하면 True.

        벡터를 쓸 수 없는 경우(서명 불일치)와, 쓸 수는 있으나 청크가 지금 기준보다 크게 잡혀 있는
        경우를 모두 포함한다. 화면은 이 값으로 안내하고, 검색은 vector_index_usable 만 본다.
        """
        if not self.vector_index_usable:
            return True
        expected = self.expected_chunk_chars
        return expected is not None and expected != self.indexed_chunk_chars


# 매 Gemini 호출마다 DB를 읽지 않도록 프로세스 안에 들고 있는다. 값을 바꾸는 경로가 save_settings
# 하나뿐이라 그 자리에서 갱신하면 일관성이 유지된다. 다만 워커를 여러 개 띄우면 다른 워커의 캐시는
# 갱신되지 않으므로, 설정 변경을 즉시 반영하려면 단일 워커로 띄워야 한다.
_cache: RuntimeSettings | None = None


def load_settings(db: Session) -> RuntimeSettings:
    """DB에 저장된 값에 .env 폴백을 씌워 지금 유효한 설정을 만든다. 캐시를 거치지 않는다."""
    stored = {row.key: row.value for row in db.query(AppSetting).all()}
    embedding_model = stored.get(EMBEDDING_MODEL) or settings.embedding_model
    return RuntimeSettings(
        gemini_api_key=stored.get(API_KEY) or settings.gemini_api_key,
        embedding_model=embedding_model,
        query_rewrite_model=stored.get(QUERY_REWRITE_MODEL) or settings.query_rewrite_model,
        answer_model=stored.get(ANSWER_MODEL) or settings.answer_model,
        embedding_provider=_parse_provider(stored.get(EMBEDDING_PROVIDER)),
        tei_base_url=stored.get(TEI_BASE_URL) or "",
        tei_model=stored.get(TEI_MODEL) or "",
        # 재색인을 한 번도 하지 않은 환경은 Gemini로 EMBEDDING_DIM 차원으로 쌓여 있다. 그것이
        # 이 기능이 없던 시절의 유일한 가능성이라, 그 상태를 기록된 값처럼 취급한다.
        indexed_dim=_parse_dim(stored.get(INDEXED_DIM)),
        indexed_signature=stored.get(INDEXED_SIGNATURE)
        or f"{EmbeddingProvider.GEMINI.value}:{settings.embedding_model}",
        indexed_chunk_chars=_parse_int(stored.get(INDEXED_CHUNK_CHARS), LEGACY_CHUNK_CHARS),
    )


def _parse_provider(value: str | None) -> EmbeddingProvider:
    """저장된 provider 문자열을 해석한다. 알 수 없는 값이면 기본값으로 되돌린다.

    저장 시점에 검증하므로 정상 경로에서는 걸리지 않지만, DB를 직접 고친 경우에 여기서 죽으면
    설정 화면조차 열 수 없어 되돌릴 방법이 없어진다.
    """
    if value is None:
        return DEFAULT_EMBEDDING_PROVIDER
    try:
        return EmbeddingProvider(value)
    except ValueError:
        logger.warning("unknown embedding provider stored, falling back: {!r}", value)
        return DEFAULT_EMBEDDING_PROVIDER


def _parse_dim(value: str | None) -> int:
    return _parse_int(value, settings.embedding_dim)


def _parse_int(value: str | None, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        logger.warning("unparsable stored integer, falling back to {}: {!r}", fallback, value)
        return fallback


def get_settings() -> RuntimeSettings:
    """지금 유효한 설정을 돌려준다. Gemini를 호출하는 서비스들이 모델명·API key를 여기서 읽는다.

    db 세션을 받지 않는다. 호출하는 쪽(services.answer 등)이 세션을 들고 있지 않은데, 설정을 읽기
    위해 그 함수들에 db를 흘려보내면 서비스 시그니처가 전부 바뀐다.
    """
    global _cache
    if _cache is None:
        with SessionLocal() as db:
            _cache = load_settings(db)
    return _cache


def save_settings(updates: dict[str, str], db: Session) -> RuntimeSettings:
    """넘긴 항목만 DB에 덮어쓰고 갱신된 설정을 돌려준다. 캐시도 이 자리에서 갱신한다."""
    unknown = set(updates) - SETTING_KEYS
    if unknown:
        raise ValueError(f"unknown setting key(s): {sorted(unknown)}")

    # 부분 갱신이라 항목 하나만 봐서는 결과가 성립하는지 알 수 없다. 저장된 값과 합친 뒤에 본다.
    current = load_settings(db)
    provider = _parse_provider(updates.get(EMBEDDING_PROVIDER) or current.embedding_provider.value)
    base_url = updates.get(TEI_BASE_URL, current.tei_base_url)
    if provider is EmbeddingProvider.TEI and not base_url:
        raise ValueError("tei_base_url is required when embedding_provider is tei")

    return _write(updates, db)


def save_index_state(dim: int, signature: str, chunk_chars: int, db: Session) -> RuntimeSettings:
    """색인이 어떤 임베딩으로 어떻게 잘려 만들어졌는지 기록한다. 재색인만 부른다."""
    return _write(
        {
            INDEXED_DIM: str(dim),
            INDEXED_SIGNATURE: signature,
            INDEXED_CHUNK_CHARS: str(chunk_chars),
        },
        db,
    )


def _write(updates: dict[str, str], db: Session) -> RuntimeSettings:
    global _cache

    for key, value in updates.items():
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()

    _cache = load_settings(db)
    return _cache


def reset_cache() -> None:
    """캐시를 버려 다음 조회에서 DB를 다시 읽게 한다. 테스트에서 격리를 위해 쓴다."""
    global _cache
    _cache = None


def describe_settings(db: Session) -> SettingsResponse:
    """설정 화면이 그릴 수 있도록 지금 값과 선택지를 함께 담아 돌려준다."""
    current = load_settings(db)
    return SettingsResponse(
        answer_model=current.answer_model,
        query_rewrite_model=current.query_rewrite_model,
        embedding_model=current.embedding_model,
        embedding_provider=current.embedding_provider,
        tei_base_url=current.tei_base_url,
        tei_model=current.tei_model,
        embedding_dim=settings.embedding_dim,
        indexed_dim=current.indexed_dim,
        indexed_chunk_chars=current.indexed_chunk_chars,
        expected_chunk_chars=current.expected_chunk_chars,
        reindex_required=current.reindex_required,
        vector_search_active=current.vector_index_usable,
        api_key_configured=bool(current.gemini_api_key),
        api_key_hint=_mask_api_key(current.gemini_api_key),
        embedding_providers=[
            ProviderOption(id=provider.value, label=label) for provider, label in PROVIDER_LABELS.items()
        ],
        generation_models=_with_current(
            [ModelOption(id=option.id, label=option.label) for option in GENERATION_MODELS],
            (current.answer_model, current.query_rewrite_model),
        ),
        embedding_models=_with_current(
            [ModelOption(id=option.id, label=option.label) for option in EMBEDDING_MODELS],
            (current.embedding_model,),
        ),
    )


def _mask_api_key(api_key: str) -> str | None:
    """저장된 키를 알아볼 수 있을 만큼만 남긴다. 짧은 키는 끝자리도 보여주지 않는다."""
    if not api_key:
        return None
    return f"…{api_key[-4:]}" if len(api_key) > 8 else "…"


def _with_current(options: list[ModelOption], current_ids: tuple[str, ...]) -> list[ModelOption]:
    """지금 쓰는 모델이 상수 목록에 없으면 선택지에 더한다.

    .env로 목록 밖의 모델을 지정할 수 있으므로(core.model_catalog) 이 처리가 없으면 화면의 선택
    상자가 지금 값을 표시할 수 없어, 설정 화면을 열어 저장하는 것만으로 모델이 조용히 바뀐다.
    """
    known = {option.id for option in options}
    extra = [
        ModelOption(id=model_id, label=f"{model_id} (.env 지정)")
        for model_id in dict.fromkeys(current_ids)
        if model_id not in known
    ]
    return extra + options
