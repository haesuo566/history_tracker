"""기간이 걸린 검색이 무엇을 남기고 무엇을 떨어뜨리는지."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db.base import Base
from backend.db.init_db import CHUNK_FTS_DDL
from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.services import search as search_service
from backend.services.search import _fts_search, list_recent, search_history
from backend.services.timerange import TimeRange, TimeRangeKind, resolve

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=KST)

# documents.timestamp 는 오프셋 없는 UTC 로 저장된다(services/document.py).
TODAY = datetime(2026, 8, 31, 3, 0)  # 8/31 12:00 KST
YESTERDAY = datetime(2026, 8, 29, 20, 0)  # 8/30 05:00 KST
LAST_MONTH = datetime(2026, 7, 10, 1, 0)

TITLE = "리액트 훅 정리"
BODY = "useEffect 의존성 배열을 비우면 마운트에만 실행된다"


def window(kind: TimeRangeKind = TimeRangeKind.YESTERDAY, **fields):
    return resolve(TimeRange(kind=kind, **fields), NOW)


@pytest.fixture
def db():
    """같은 제목·본문의 문서 셋이 서로 다른 날에 수집돼 있는 DB. 갈리는 것은 시각뿐이다."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[Document.__table__, Chunk.__table__])
    with Session(engine) as session:
        session.execute(text(CHUNK_FTS_DDL))
        for document_id, collected_at in (
            ("doc-today", TODAY),
            ("doc-yesterday", YESTERDAY),
            ("doc-old", LAST_MONTH),
        ):
            session.add(
                Document(
                    document_id=document_id,
                    url=f"https://example.com/{document_id}",
                    title=TITLE,
                    full_text=BODY,
                    hash=f"hash-{document_id}",
                    timestamp=collected_at,
                )
            )
            session.execute(
                text("INSERT INTO chunk_fts (vector_key, title, body) VALUES (:key, :title, :body)"),
                {"key": f"{document_id}:0", "title": TITLE, "body": BODY},
            )
        session.commit()
        yield session


@pytest.fixture
def vector_hits(monkeypatch):
    """벡터 검색을 대체한다. 돌려줄 청크와, 그쪽이 받은 limit 을 담는 자리를 준다."""
    state: dict = {"keys": [], "limit": None}

    def fake_vector_search(db, query, limit):
        state["limit"] = limit
        return list(state["keys"])

    monkeypatch.setattr(search_service, "_vector_search_if_usable", fake_vector_search)
    return state


def found(results) -> list[str]:
    return [result.document_id for result in results]


def test_the_full_text_search_filters_inside_sql(db):
    """뽑아 온 뒤에 거르면 상위 limit 건이 기간 밖 문서로 채워져 그 기간의 문서가 밀려난다."""
    assert _fts_search(db, ["리액트"], 50, window()) == [("doc-yesterday", 0)]


def test_without_a_period_the_full_text_search_sees_everything(db):
    assert sorted(_fts_search(db, ["리액트"], 50)) == [
        ("doc-old", 0),
        ("doc-today", 0),
        ("doc-yesterday", 0),
    ]


def test_vector_hits_outside_the_period_are_dropped(db, vector_hits):
    """벡터 쪽은 vec0 가상 테이블이라 조인이 안 된다. 뽑아 온 뒤 문서의 수집 시각으로 거른다."""
    vector_hits["keys"] = [("doc-today", 0), ("doc-yesterday", 0), ("doc-old", 0)]

    results = search_history("리액트", db, window=window())

    assert found(results) == ["doc-yesterday"]


def test_the_vector_search_is_widened_when_a_period_is_set(db, vector_hits):
    """거를 것을 감안하지 않으면, 뽑아 온 50건이 죄다 기간 밖이라 0건이 되는 일이 생긴다."""
    search_history("리액트", db, limit=50, window=window())

    assert vector_hits["limit"] == 50 * search_service.FILTERED_VECTOR_LIMIT_FACTOR


def test_an_unbounded_search_keeps_the_original_limit(db, vector_hits):
    search_history("리액트", db, limit=50)

    assert vector_hits["limit"] == 50


def test_a_period_with_no_match_stays_empty(db, vector_hits):
    """사용자는 '어제 본 것'을 물었다. 기간을 풀어 그저께 것을 내놓으면 어제 것으로 오해한 채 읽는다."""
    vector_hits["keys"] = [("doc-today", 0), ("doc-old", 0)]

    results = search_history("쿠버네티스", db, window=window(TimeRangeKind.ABSOLUTE, since="2026-01-01", until="2026-01-02"))

    assert results == []


def test_listing_shows_the_period_newest_first(db):
    results = list_recent(window(TimeRangeKind.THIS_MONTH), db)

    assert found(results) == ["doc-today", "doc-yesterday"]  # doc-old 는 지난달이다


def test_listing_respects_a_requested_count(db):
    results = list_recent(window(TimeRangeKind.THIS_MONTH), db, count=1)

    assert found(results) == ["doc-today"]


def test_listing_carries_a_snippet_from_the_body(db):
    results = list_recent(window(), db)

    assert results[0].snippet.startswith("useEffect")
