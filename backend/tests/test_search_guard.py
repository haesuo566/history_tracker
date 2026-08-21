"""임베딩을 바꾸고 재색인하지 않은 상태에서 검색이 어떻게 버티는지."""

import pytest

from backend.services import search as search_service
from backend.services.search import _vector_search_if_usable
from tests.test_runtime_settings import runtime_settings


@pytest.fixture
def spy(monkeypatch):
    """embed_query 와 _vector_search 를 가로채 실제로 불렸는지만 기록한다."""
    seen: dict[str, bool] = {}

    def fake_embed_query(text: str) -> list[float]:
        seen["embedded"] = True
        return [0.1, 0.2]

    def fake_vector_search(db, embedding, limit):
        seen["searched"] = True
        return [("doc-a", 0)]

    monkeypatch.setattr(search_service, "embed_query", fake_embed_query)
    monkeypatch.setattr(search_service, "_vector_search", fake_vector_search)
    return seen


def use_settings(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(search_service, "get_settings", lambda: runtime_settings(**overrides))


def test_a_matching_index_is_searched_normally(spy, monkeypatch):
    use_settings(monkeypatch)

    assert _vector_search_if_usable(None, "리액트", 50) == [("doc-a", 0)]
    assert spy == {"embedded": True, "searched": True}


def test_a_different_chunk_size_still_uses_the_vector_search(spy, monkeypatch):
    """청크 경계가 예전 기준이어도 좌표는 같은 모델이 만든 것이다. 검색을 끌 이유가 없다."""
    use_settings(monkeypatch, indexed_chunk_chars=8192)

    assert _vector_search_if_usable(None, "리액트", 50) == [("doc-a", 0)]
    assert spy == {"embedded": True, "searched": True}


def test_a_stale_index_skips_the_vector_search(spy, monkeypatch):
    """차원이 다르면 sqlite-vec 가 오류를 내며 검색 전체가 실패한다. 전문 검색만으로 답한다."""
    use_settings(monkeypatch, indexed_signature="gemini:gemini-embedding-001", embedding_model="gemini-embedding-2")

    assert _vector_search_if_usable(None, "리액트", 50) == []
    assert spy == {}


def test_a_stale_index_does_not_even_call_the_embedder(spy, monkeypatch):
    """쓰지도 못할 벡터를 받으려고 TEI나 Gemini를 부르는 것은 낭비이고, 그쪽이 죽어 있으면 잡담까지 막힌다."""
    use_settings(monkeypatch, indexed_signature="tei:BAAI/bge-m3")

    _vector_search_if_usable(None, "리액트", 50)

    assert "embedded" not in spy
