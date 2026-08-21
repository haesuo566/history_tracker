import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.api.routes import settings as settings_route
from backend.core.config import settings
from backend.core.model_catalog import chunk_chars_for
from backend.db.base import Base
from backend.db.session import get_db
from backend.models.app_setting import AppSetting
from backend.services.runtime_settings import reset_cache


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[AppSetting.__table__])
    reset_cache()

    app = FastAPI()
    app.include_router(settings_route.router)
    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as test_client:
            yield test_client
    reset_cache()


def get(client: TestClient) -> dict:
    response = client.get("/settings")
    assert response.status_code == 200, response.text
    return response.json()


def patch(client: TestClient, body: dict) -> dict:
    response = client.patch("/settings", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_get_reports_the_models_in_effect(client):
    body = get(client)

    assert body["answer_model"] == settings.answer_model
    assert body["query_rewrite_model"] == settings.query_rewrite_model
    assert body["embedding_model"] == settings.embedding_model


def test_get_carries_the_choices_and_the_indexed_dimension(client):
    """화면이 선택 상자와 재색인 경고를 그리려면 이 둘이 함께 와야 한다."""
    body = get(client)

    assert len(body["generation_models"]) > 1
    assert len(body["embedding_models"]) >= 1
    assert body["embedding_dim"] == settings.embedding_dim


def test_get_never_carries_the_api_key(client):
    body = client.get("/settings")

    assert settings.gemini_api_key not in body.text
    assert body.json()["api_key_configured"] is True


def test_patching_a_model_takes_effect(client):
    body = patch(client, {"answer_model": "gemini-2.5-pro"})

    assert body["answer_model"] == "gemini-2.5-pro"
    assert get(client)["answer_model"] == "gemini-2.5-pro"


def test_patching_one_model_leaves_the_others_alone(client):
    """화면은 바꾼 항목만 보내므로, 보내지 않은 항목이 초기화되면 안 된다."""
    patch(client, {"answer_model": "gemini-2.5-pro"})

    body = get(client)
    assert body["query_rewrite_model"] == settings.query_rewrite_model
    assert body["embedding_model"] == settings.embedding_model


def test_an_empty_patch_changes_nothing(client):
    body = patch(client, {})

    assert body["answer_model"] == settings.answer_model


def test_an_unknown_model_is_rejected(client):
    """오타 난 모델명을 저장해두면 다음 질의부터 전부 실패한다. 저장 시점에 막는다."""
    response = client.patch("/settings", json={"answer_model": "gpt-4"})

    assert response.status_code == 422
    assert get(client)["answer_model"] == settings.answer_model


def test_an_embedding_model_that_cannot_reach_the_indexed_dimension_is_rejected(client, monkeypatch):
    """차원을 못 내는 모델로 바꾸면 저장은 되고 색인만 조용히 전부 실패한다."""
    monkeypatch.setattr(settings, "embedding_dim", 8192)

    response = client.patch("/settings", json={"embedding_model": "gemini-embedding-001"})

    assert response.status_code == 422


def test_a_new_api_key_is_stored_and_only_hinted_back(client):
    body = patch(client, {"gemini_api_key": "AIzaSyNEWKEY9876"})

    assert body["api_key_hint"] == "…9876"
    assert "AIzaSyNEWKEY9876" not in client.get("/settings").text


def test_omitting_the_api_key_keeps_the_stored_one(client):
    """화면은 저장된 키 원문을 모르므로 모델만 바꾸는 저장에서 키를 함께 보낼 수 없다."""
    patch(client, {"gemini_api_key": "AIzaSyNEWKEY9876"})

    body = patch(client, {"answer_model": "gemini-2.5-pro"})

    assert body["api_key_hint"] == "…9876"


def test_get_reports_the_provider_and_index_state(client):
    body = get(client)

    assert body["embedding_provider"] == "gemini"
    assert body["indexed_dim"] == settings.embedding_dim
    assert [option["id"] for option in body["embedding_providers"]] == ["gemini", "tei"]


def test_get_reports_the_chunk_size(client):
    """예전 색인은 8192자로 쌓여 있고, 지금 기준은 모델 한계에서 환산한 값이다."""
    body = get(client)

    assert body["indexed_chunk_chars"] == 8192
    assert body["expected_chunk_chars"] == chunk_chars_for(2048)
    assert body["reindex_required"] is True
    # 벡터 자체는 같은 모델이 만든 것이라 검색은 계속 쓴다.
    assert body["vector_search_active"] is True


def test_switching_the_provider_turns_off_the_vector_search(client):
    body = patch(client, {"embedding_provider": "tei", "tei_base_url": "http://tei:8080"})

    assert body["vector_search_active"] is False
    assert body["expected_chunk_chars"] is None


def test_switching_to_tei_needs_an_address(client):
    """주소 없이 넘어가면 저장은 되고 색인·검색만 조용히 전부 실패한다."""
    response = client.patch("/settings", json={"embedding_provider": "tei"})

    assert response.status_code == 422
    assert get(client)["embedding_provider"] == "gemini"


def test_switching_to_tei_with_an_address_flags_a_reindex(client):
    body = patch(client, {"embedding_provider": "tei", "tei_base_url": "http://tei:8080"})

    assert body["embedding_provider"] == "tei"
    assert body["tei_base_url"] == "http://tei:8080"
    assert body["reindex_required"] is True


def test_a_trailing_slash_in_the_address_is_trimmed(client):
    body = patch(client, {"embedding_provider": "tei", "tei_base_url": "http://tei:8080/"})

    assert body["tei_base_url"] == "http://tei:8080"


def test_an_address_without_a_scheme_is_rejected(client):
    """host:port 만 넣으면 httpx 가 상대 URL 로 보고 엉뚱한 곳을 부른다."""
    response = client.patch("/settings", json={"embedding_provider": "tei", "tei_base_url": "tei:8080"})

    assert response.status_code == 422


def test_an_unknown_provider_is_rejected(client):
    response = client.patch("/settings", json={"embedding_provider": "ollama"})

    assert response.status_code == 422


def test_a_blank_api_key_is_rejected(client):
    """키 없이는 어떤 질의도 처리할 수 없다. 잘못 눌러 앱이 멈추는 쪽이 손해가 크다."""
    patch(client, {"gemini_api_key": "AIzaSyNEWKEY9876"})

    response = client.patch("/settings", json={"gemini_api_key": "   "})

    assert response.status_code == 422
    assert get(client)["api_key_hint"] == "…9876"
