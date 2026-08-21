import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.core.config import settings
from backend.core.model_catalog import EmbeddingProvider, chunk_chars_for
from backend.db.base import Base
from backend.models.app_setting import AppSetting
from backend.services import gemini as gemini_service
from backend.services import runtime_settings as runtime_settings_module
from backend.services.runtime_settings import (
    LEGACY_CHUNK_CHARS,
    RuntimeSettings,
    describe_settings,
    get_settings,
    load_settings,
    reset_cache,
    save_index_state,
    save_settings,
)

# gemini-embedding-001 의 입력 한계 2048토큰을 환산한 값. 기본값을 '색인과 설정이 맞는' 상태로
# 두어야, 어긋난 상황을 보는 테스트가 무엇을 어긋냈는지 분명해진다.
MATCHING_CHUNK_CHARS = chunk_chars_for(2048)


def runtime_settings(**overrides) -> RuntimeSettings:
    """캐시에 직접 심을 RuntimeSettings. 필드가 늘어도 테스트가 깨지지 않게 기본값을 모아 둔다."""
    base = {
        "gemini_api_key": "test-key",
        "embedding_model": "gemini-embedding-001",
        "query_rewrite_model": "gemini-3.1-flash-lite",
        "answer_model": "gemini-3.1-flash-lite",
        "embedding_provider": EmbeddingProvider.GEMINI,
        "tei_base_url": "",
        "tei_model": "",
        "indexed_dim": 3072,
        "indexed_signature": "gemini:gemini-embedding-001",
        "indexed_chunk_chars": MATCHING_CHUNK_CHARS,
    }
    return RuntimeSettings(**(base | overrides))


@pytest.fixture
def db():
    """app_settings 하나만 있는 인메모리 DB. 전역 캐시는 테스트마다 비운다."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[AppSetting.__table__])
    reset_cache()
    with Session(engine) as session:
        yield session
    reset_cache()


def test_an_empty_table_falls_back_to_the_env_file(db):
    """설정 화면을 한 번도 쓰지 않은 환경의 동작이 예전과 같아야 한다."""
    current = load_settings(db)

    assert current.answer_model == settings.answer_model
    assert current.query_rewrite_model == settings.query_rewrite_model
    assert current.embedding_model == settings.embedding_model
    assert current.gemini_api_key == settings.gemini_api_key


def test_a_stored_value_wins_over_the_env_file(db):
    save_settings({"answer_model": "gemini-2.5-pro"}, db)

    assert load_settings(db).answer_model == "gemini-2.5-pro"


def test_untouched_items_keep_falling_back(db):
    """부분 갱신이므로 저장하지 않은 항목은 .env 값을 그대로 써야 한다."""
    save_settings({"answer_model": "gemini-2.5-pro"}, db)

    current = load_settings(db)
    assert current.query_rewrite_model == settings.query_rewrite_model
    assert current.embedding_model == settings.embedding_model


def test_saving_twice_overwrites_instead_of_piling_up(db):
    save_settings({"answer_model": "gemini-2.5-pro"}, db)
    save_settings({"answer_model": "gemini-2.5-flash"}, db)

    assert load_settings(db).answer_model == "gemini-2.5-flash"
    assert db.query(AppSetting).count() == 1


def test_saving_refreshes_the_cache(db):
    """캐시가 남아 있으면 저장 직후의 질의가 예전 모델로 나간다."""
    save_settings({"answer_model": "gemini-2.5-pro"}, db)

    assert get_settings().answer_model == "gemini-2.5-pro"


def test_an_unknown_key_is_rejected(db):
    """키 이름이 틀리면 조용히 무시되는 대신 알려야 한다. 저장한 줄 알고 넘어가는 쪽이 나쁘다."""
    with pytest.raises(ValueError, match="unknown setting key"):
        save_settings({"answer_mdoel": "gemini-2.5-pro"}, db)


def test_the_api_key_is_never_returned_in_full(db):
    """설정 화면을 여는 것만으로 키가 응답 본문을 타고 흐르면 안 된다."""
    save_settings({"gemini_api_key": "AIzaSyTESTKEY1234"}, db)

    described = describe_settings(db)

    assert described.api_key_configured is True
    assert described.api_key_hint == "…1234"
    assert "AIzaSyTESTKEY1234" not in described.model_dump_json()


def test_a_short_api_key_hides_even_its_tail(db):
    """짧은 키는 끝 네 자리가 키의 대부분이다."""
    save_settings({"gemini_api_key": "short"}, db)

    assert describe_settings(db).api_key_hint == "…"


def test_a_missing_api_key_is_reported_as_unconfigured(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")

    described = describe_settings(db)

    assert described.api_key_configured is False
    assert described.api_key_hint is None


def test_a_model_set_only_in_the_env_file_still_appears_as_a_choice(db, monkeypatch):
    """선택지에 없으면 화면이 지금 값을 표시할 수 없어, 저장만으로 모델이 조용히 바뀐다."""
    monkeypatch.setattr(settings, "answer_model", "gemini-experimental-9")

    described = describe_settings(db)

    assert described.answer_model == "gemini-experimental-9"
    assert "gemini-experimental-9" in [option.id for option in described.generation_models]


def test_the_choice_list_has_no_duplicates_when_both_models_are_custom(db, monkeypatch):
    monkeypatch.setattr(settings, "answer_model", "gemini-experimental-9")
    monkeypatch.setattr(settings, "query_rewrite_model", "gemini-experimental-9")

    ids = [option.id for option in describe_settings(db).generation_models]

    assert ids.count("gemini-experimental-9") == 1


def test_changing_the_api_key_rebuilds_the_gemini_client(db, monkeypatch):
    """키를 바꿔도 예전 클라이언트가 남아 있으면 새 키가 적용되지 않는다."""
    built = []
    monkeypatch.setattr(gemini_service, "_client", None)
    monkeypatch.setattr(gemini_service, "_client_api_key", None)
    monkeypatch.setattr(gemini_service.genai, "Client", lambda api_key: built.append(api_key) or object())

    save_settings({"gemini_api_key": "key-one"}, db)
    gemini_service.get_client()
    gemini_service.get_client()  # 같은 키로는 다시 만들지 않는다
    save_settings({"gemini_api_key": "key-two"}, db)
    gemini_service.get_client()

    assert built == ["key-one", "key-two"]


def test_the_provider_defaults_to_gemini(db):
    """provider 항목이 없던 시절의 DB 는 Gemini 로 돌고 있었다."""
    assert load_settings(db).embedding_provider is EmbeddingProvider.GEMINI


def test_switching_to_tei_requires_an_address(db):
    """주소 없이 TEI 로 넘기면 저장은 되고 색인·검색만 전부 실패한다."""
    with pytest.raises(ValueError, match="tei_base_url is required"):
        save_settings({"embedding_provider": "tei"}, db)

    assert load_settings(db).embedding_provider is EmbeddingProvider.GEMINI


def test_switching_to_tei_with_an_address_is_stored(db):
    save_settings({"embedding_provider": "tei", "tei_base_url": "http://tei:8080"}, db)

    current = load_settings(db)
    assert current.embedding_provider is EmbeddingProvider.TEI
    assert current.tei_base_url == "http://tei:8080"


def test_the_address_can_be_saved_before_switching(db):
    """주소를 먼저 넣고 나중에 전환하는 순서도 막지 않는다."""
    save_settings({"tei_base_url": "http://tei:8080"}, db)
    save_settings({"embedding_provider": "tei"}, db)

    assert load_settings(db).embedding_provider is EmbeddingProvider.TEI


def test_an_unknown_stored_provider_falls_back_instead_of_crashing(db):
    """여기서 죽으면 설정 화면조차 열 수 없어 되돌릴 방법이 사라진다."""
    db.add(AppSetting(key="embedding_provider", value="ollama"))
    db.commit()

    assert load_settings(db).embedding_provider is EmbeddingProvider.GEMINI


def test_switching_the_provider_asks_for_a_reindex(db):
    """예전 벡터는 다른 공간의 좌표다. 그대로 검색에 쓸 수 없다."""
    save_settings({"embedding_provider": "tei", "tei_base_url": "http://tei:8080"}, db)

    assert load_settings(db).reindex_required is True


def test_an_index_built_with_the_old_chunk_size_asks_for_a_reindex(db):
    """청크 크기를 기록하기 전의 색인은 8192자로 쌓여 있다. 그건 임베딩 한계를 넘는 크기였다."""
    current = load_settings(db)

    assert current.indexed_chunk_chars == LEGACY_CHUNK_CHARS
    assert current.reindex_required is True
    # 다만 벡터 자체는 같은 모델이 만든 것이라 검색에 쓸 수 있다.
    assert current.vector_index_usable is True


def test_a_matching_chunk_size_does_not_ask_for_a_reindex(db):
    save_index_state(3072, "gemini:gemini-embedding-001", MATCHING_CHUNK_CHARS, db)

    assert load_settings(db).reindex_required is False


def test_the_chunk_size_comes_from_the_model_input_limit(db):
    """gemini-embedding-001 은 2048토큰, gemini-embedding-2 는 8192토큰을 받는다."""
    assert load_settings(db).expected_chunk_chars == chunk_chars_for(2048)

    save_settings({"embedding_model": "gemini-embedding-2"}, db)

    assert load_settings(db).expected_chunk_chars == chunk_chars_for(8192)


def test_the_chunk_size_is_unknown_for_tei(db):
    """TEI 의 입력 한계는 서버에 물어야 안다. 여기서 추측하면 조용히 잘린 색인이 된다."""
    save_settings({"embedding_provider": "tei", "tei_base_url": "http://tei:8080"}, db)

    assert load_settings(db).expected_chunk_chars is None


def test_tei_with_a_matching_signature_does_not_ask_for_a_reindex(db):
    """서명이 같으면 같은 서버·같은 모델이다. 청크 크기를 다시 물어 확인할 이유가 없다."""
    save_settings(
        {"embedding_provider": "tei", "tei_base_url": "http://tei:8080", "tei_model": "BAAI/bge-m3"}, db
    )
    save_index_state(1024, "tei:BAAI/bge-m3", 9011, db)

    assert load_settings(db).reindex_required is False


def test_changing_the_gemini_embedding_model_asks_for_a_reindex(db):
    """제공자가 그대로여도 모델이 바뀌면 벡터 공간이 달라진다."""
    save_settings({"embedding_model": "gemini-embedding-2"}, db)

    assert load_settings(db).reindex_required is True


def test_recording_the_index_state_clears_the_reindex_flag(db):
    save_settings({"embedding_provider": "tei", "tei_base_url": "http://tei:8080"}, db)

    save_index_state(1024, "tei:http://tei:8080", 9011, db)

    current = load_settings(db)
    assert current.reindex_required is False
    assert current.indexed_dim == 1024
    assert current.indexed_chunk_chars == 9011


def test_the_tei_signature_prefers_the_model_over_the_address(db):
    """같은 서버 주소로 다른 모델을 올릴 수 있다. 모델명을 적었으면 그것이 더 정확한 서명이다."""
    save_settings(
        {"embedding_provider": "tei", "tei_base_url": "http://tei:8080", "tei_model": "BAAI/bge-m3"}, db
    )

    assert load_settings(db).embedding_signature == "tei:BAAI/bge-m3"


def test_index_state_keys_cannot_be_set_through_settings(db):
    """색인 상태는 설정이 아니라 재색인의 결과다. 설정 화면이 손대면 서명만 맞춰 놓고 색인은 예전
    벡터인 상태를 만들 수 있다."""
    with pytest.raises(ValueError, match="unknown setting key"):
        save_settings({"indexed_embedding_signature": "tei:BAAI/bge-m3"}, db)


def test_a_blank_api_key_fails_with_a_clear_message(monkeypatch):
    """키가 없으면 첫 Gemini 호출에서 맥락 없는 오류가 나는 대신 무엇을 해야 하는지 알려야 한다."""
    # 캐시를 비우면 get_settings가 운영 DB를 읽으러 가므로, 여기서는 캐시를 직접 채운다.
    monkeypatch.setattr(runtime_settings_module, "_cache", runtime_settings(gemini_api_key=""))
    monkeypatch.setattr(gemini_service, "_client", None)

    with pytest.raises(RuntimeError, match="API key"):
        gemini_service.get_client()
