"""전문 검색이 제목과 본문을 어떻게 함께 다루는지."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db.init_db import CHUNK_FTS_DDL
from backend.services import search as search_service
from backend.services.search import _fts_search

TITLE = "리액트 훅 정리"
BODY = "useEffect 의존성 배열을 비우면 마운트에만 실행된다"


@pytest.fixture
def db():
    """chunk_fts 한 행이 들어 있는 인메모리 DB. vec_chunks 는 이 테스트와 무관해 만들지 않는다."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with Session(engine) as session:
        session.execute(text(CHUNK_FTS_DDL))
        session.execute(
            text("INSERT INTO chunk_fts (vector_key, title, body) VALUES ('doc-a:0', :title, :body)"),
            {"title": TITLE, "body": BODY},
        )
        session.commit()
        yield session


def require_matches(monkeypatch, count: int) -> None:
    monkeypatch.setattr(search_service.settings, "min_fts_matched_terms", count)


def test_a_word_only_in_the_title_is_found(db, monkeypatch):
    """제목이 색인에 들어간 이유. 예전에는 제목으로 걸려도 본문 매칭이 0이라 전부 걸러졌다."""
    require_matches(monkeypatch, 1)

    assert _fts_search(db, ["리액트"], 50) == [("doc-a", 0)]


def test_a_word_only_in_the_body_is_still_found(db, monkeypatch):
    require_matches(monkeypatch, 1)

    assert _fts_search(db, ["의존성"], 50) == [("doc-a", 0)]


def test_a_word_in_neither_is_not_found(db, monkeypatch):
    require_matches(monkeypatch, 1)

    assert _fts_search(db, ["쿠버네티스"], 50) == []


def test_title_and_body_matches_add_up_to_pass_the_guard(db, monkeypatch):
    """매칭 단어 수는 제목과 본문을 합쳐서 센다."""
    require_matches(monkeypatch, 2)

    assert _fts_search(db, ["리액트", "의존성"], 50) == [("doc-a", 0)]


def test_a_weak_match_is_still_dropped(db, monkeypatch):
    """한 단어만 걸리면 약한 매칭이다 — 가드는 그대로 살아 있어야 한다."""
    require_matches(monkeypatch, 2)

    assert _fts_search(db, ["리액트", "쿠버네티스"], 50) == []


def test_no_nouns_means_no_query(db):
    assert _fts_search(db, [], 50) == []
