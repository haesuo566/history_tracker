"""색인 배치가 어떤 청크 크기로 자르는지. 그 크기를 정하는 것은 재색인이다."""

import pytest
import sqlite_vec
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db.base import Base
from backend.db.init_db import CHUNK_FTS_DDL, vec_chunks_ddl
from backend.models.app_setting import AppSetting
from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.services import indexing as indexing_service
from backend.services.indexing import run_indexing_batch
from backend.services.runtime_settings import reset_cache, save_index_state

DIM = 4
BODY_CHARS = 1000


@pytest.fixture
def db(monkeypatch):
    """문서 한 건이 색인 대기로 들어 있는 인메모리 DB. 임베딩은 고정 벡터로 대신한다."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _load_sqlite_vec(dbapi_connection, connection_record) -> None:
        dbapi_connection.enable_load_extension(True)
        sqlite_vec.load(dbapi_connection)
        dbapi_connection.enable_load_extension(False)

    Base.metadata.create_all(
        bind=engine, tables=[Document.__table__, Chunk.__table__, AppSetting.__table__]
    )
    reset_cache()

    monkeypatch.setattr(
        indexing_service, "embed_texts", lambda texts: [[0.1] * DIM for _ in texts]
    )

    with Session(engine) as session:
        session.execute(text(vec_chunks_ddl(DIM)))
        session.execute(text(CHUNK_FTS_DDL))
        session.add(
            Document(
                document_id="doc-a",
                url="https://example.com/a",
                title="긴 문서",
                full_text="가" * BODY_CHARS,
                hash="hash-a",
                checked=False,
            )
        )
        session.commit()
        yield session

    reset_cache()


def chunk_count(db: Session) -> int:
    return db.execute(text("SELECT count(*) FROM chunks")).scalar_one()


def test_the_recorded_chunk_size_decides_the_split(db):
    """색인 배치가 제 기준으로 자르면, 재색인이 정한 크기와 어긋난 청크가 색인에 섞인다."""
    save_index_state(DIM, "gemini:gemini-embedding-001", 250, db)

    result = run_indexing_batch(db)

    assert result.succeeded == 1
    assert chunk_count(db) == BODY_CHARS // 250


def test_a_larger_chunk_size_makes_fewer_chunks(db):
    save_index_state(DIM, "gemini:gemini-embedding-001", 500, db)

    run_indexing_batch(db)

    assert chunk_count(db) == BODY_CHARS // 500


def test_the_fts_rows_follow_the_same_split(db):
    """전문 색인이 청크와 짝이 맞지 않으면 검색이 없는 청크를 가리킨다."""
    save_index_state(DIM, "gemini:gemini-embedding-001", 250, db)

    run_indexing_batch(db)

    fts_rows = db.execute(text("SELECT count(*) FROM chunk_fts")).scalar_one()
    vectors = db.execute(text("SELECT count(*) FROM vec_chunks")).scalar_one()
    assert fts_rows == chunk_count(db)
    assert vectors == chunk_count(db)
