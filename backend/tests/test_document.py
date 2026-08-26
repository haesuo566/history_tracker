from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.models.document import Document
from backend.schemas.collect import CollectRequest
from backend.services.document import document_hash, save_collected_document


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine, tables=[Document.__table__])
    with Session(engine) as session:
        yield session


def make_request(url: str, content: str, title: str = "t") -> CollectRequest:
    return CollectRequest(url=url, title=title, startTime=datetime.now(UTC), content=content)


def stored_urls(db: Session) -> list[str]:
    return list(db.scalars(select(Document.url).order_by(Document.id)))


def test_same_url_and_content_is_deduplicated(db):
    save_collected_document(make_request("https://a.test/1", "본문"), db)
    save_collected_document(make_request("https://a.test/1", "본문"), db)

    assert stored_urls(db) == ["https://a.test/1"]


def test_same_url_with_different_content_is_deduplicated(db):
    """광고·추천 목록처럼 본문 일부가 방문마다 달라도 같은 페이지는 한 건이다."""
    save_collected_document(make_request("https://a.test/1", "본문 조회수 1"), db)
    save_collected_document(make_request("https://a.test/1", "본문 조회수 2"), db)

    assert stored_urls(db) == ["https://a.test/1"]


def test_first_collected_content_is_kept(db):
    """재방문분은 무시하므로 먼저 수집한 본문이 남는다."""
    save_collected_document(make_request("https://a.test/1", "처음 본문"), db)
    save_collected_document(make_request("https://a.test/1", "나중 본문"), db)

    assert db.scalars(select(Document.full_text)).all() == ["처음 본문"]


def test_same_content_on_different_urls_is_kept(db):
    """기사 신디케이션처럼 본문이 같아도 URL이 다르면 별개 문서다."""
    save_collected_document(make_request("https://a.test/1", "같은 본문"), db)
    save_collected_document(make_request("https://b.test/2", "같은 본문"), db)

    assert stored_urls(db) == ["https://a.test/1", "https://b.test/2"]


def test_empty_content_does_not_block_other_pages(db):
    """본문 추출이 실패한 페이지들이 sha256('')로 충돌해 조용히 버려지던 회귀 방지."""
    save_collected_document(make_request("https://a.test/1", ""), db)
    save_collected_document(make_request("https://b.test/2", ""), db)

    assert stored_urls(db) == ["https://a.test/1", "https://b.test/2"]


def test_hash_depends_only_on_url():
    assert document_hash("https://a.test/1") != document_hash("https://b.test/2")
    assert document_hash("https://a.test/1") == document_hash("https://a.test/1")
