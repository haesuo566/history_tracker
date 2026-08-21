"""청크를 어떤 크기로 자르는지. 크기를 누가 정하는지는 test_runtime_settings 가 본다."""

from itertools import pairwise

import httpx
import pytest

from backend.core.model_catalog import (
    CHARS_PER_TOKEN,
    FALLBACK_MAX_INPUT_TOKENS,
    chunk_chars_for,
)
from backend.services import embedding as embedding_service
from backend.services import tei
from backend.services.chunking import chunk_text
from tests.test_runtime_settings import runtime_settings


def test_a_short_text_is_one_chunk():
    chunks = chunk_text("짧은 본문", max_chars=100)

    assert len(chunks) == 1
    assert chunks[0].text == "짧은 본문"
    assert (chunks[0].char_start, chunks[0].char_end) == (0, 5)


def test_a_long_text_is_split_at_the_limit():
    chunks = chunk_text("가" * 250, max_chars=100)

    assert [len(chunk.text) for chunk in chunks] == [100, 100, 50]


def test_chunks_cover_the_whole_text_without_gaps():
    """구간이 어긋나면 검색 결과의 발췌가 엉뚱한 대목을 가리킨다."""
    text = "가" * 137
    chunks = chunk_text(text, max_chars=40)

    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)
    for previous, following in pairwise(chunks):
        assert previous.char_end == following.char_start
    assert "".join(chunk.text for chunk in chunks) == text


def test_a_newline_inside_the_limit_becomes_the_boundary():
    """문장 중간에서 끊기면 그 청크만 읽고는 무슨 말인지 알 수 없다."""
    text = "첫째 줄입니다\n둘째 줄입니다\n셋째 줄입니다"
    chunks = chunk_text(text, max_chars=15)

    assert chunks[0].text == "첫째 줄입니다\n"


def test_a_line_longer_than_the_limit_is_cut_anyway():
    """개행이 없으면 자를 자리가 없다. 한계를 넘기는 것보다 중간에서 끊는 쪽이 낫다."""
    chunks = chunk_text("개행없이이어지는아주긴문장", max_chars=5)

    assert [len(chunk.text) for chunk in chunks] == [5, 5, 3]


def test_an_empty_text_makes_no_chunks():
    assert chunk_text("", max_chars=100) == []


def test_the_limit_is_converted_conservatively():
    """한국어는 1.11자/토큰까지 촘촘하다. 넘치면 오류 없이 뒷부분이 버려지므로 넉넉히 잡을 수 없다."""
    assert CHARS_PER_TOKEN <= 1.11
    assert chunk_chars_for(2048) < 2048 * 1.11


def test_gemini_chunk_size_comes_from_the_model(monkeypatch):
    monkeypatch.setattr(
        embedding_service, "get_settings", lambda: runtime_settings(embedding_model="gemini-embedding-2")
    )

    assert embedding_service.detect_chunk_chars() == chunk_chars_for(8192)


def test_an_unknown_gemini_model_falls_back_to_a_short_chunk(monkeypatch):
    """.env 로 목록 밖 모델을 지정할 수 있다. 한계를 모르면 짧게 잡아 잘리지 않는 쪽을 택한다."""
    monkeypatch.setattr(
        embedding_service, "get_settings", lambda: runtime_settings(embedding_model="gemini-future-9")
    )

    assert embedding_service.detect_chunk_chars() == chunk_chars_for(FALLBACK_MAX_INPUT_TOKENS)


@pytest.fixture
def tei_info(monkeypatch):
    """TEI /info 응답을 갈아 끼운다."""
    real_client = httpx.Client
    state: dict = {"payload": {"max_input_length": 8192}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=state["payload"])

    monkeypatch.setattr(
        tei.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return state


def test_tei_chunk_size_comes_from_the_server(monkeypatch, tei_info):
    monkeypatch.setattr(
        embedding_service,
        "get_settings",
        lambda: runtime_settings(embedding_provider="tei", tei_base_url="http://tei:8080"),
    )

    assert embedding_service.detect_chunk_chars() == chunk_chars_for(8192)


def test_a_silent_tei_falls_back_to_a_short_chunk(monkeypatch, tei_info):
    """TEI 도 auto_truncate 가 기본이라 한계를 넘기면 조용히 잘린다. 모를 때는 짧게 잡는다."""
    tei_info["payload"] = {"model_id": "BAAI/bge-m3"}
    monkeypatch.setattr(
        embedding_service,
        "get_settings",
        lambda: runtime_settings(embedding_provider="tei", tei_base_url="http://tei:8080"),
    )

    assert embedding_service.detect_chunk_chars() == chunk_chars_for(FALLBACK_MAX_INPUT_TOKENS)
