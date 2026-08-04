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
    now = datetime.now(UTC)
    return CollectRequest(url=url, title=title, startTime=now, endTime=now, content=content)


def stored_urls(db: Session) -> list[str]:
    return list(db.scalars(select(Document.url).order_by(Document.id)))


def test_same_url_and_content_is_deduplicated(db):
    save_collected_document(make_request("https://a.test/1", "본문"), db)
    save_collected_document(make_request("https://a.test/1", "본문"), db)

    assert stored_urls(db) == ["https://a.test/1"]


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


def test_hash_mixes_url_and_content():
    assert document_hash("https://a.test/1", "x") != document_hash("https://b.test/2", "x")
    assert document_hash("https://a.test/1", "x") != document_hash("https://a.test/1", "y")
    assert document_hash("https://a.test/1", "x") == document_hash("https://a.test/1", "x")
