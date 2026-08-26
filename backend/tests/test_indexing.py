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
from backend.services.indexing import MAX_TITLE_SHARE, run_indexing_batch, split_embedding_budget
from backend.services.runtime_settings import reset_cache, save_index_state

DIM = 4
BODY_CHARS = 1000
TITLE = "긴 문서"


def expected_chunks(max_chars: int, title: str = TITLE, body_chars: int = BODY_CHARS) -> int:
    """제목과 개행을 빼고 남은 몫으로 body_chars 를 자르면 몇 조각인가."""
    _, chunk_chars = split_embedding_budget(title, max_chars)
    return -(-body_chars // chunk_chars)


@pytest.fixture
def embedded():
    """임베딩에 실제로 넘어간 문자열들. db 픽스처가 채운다."""
    return []


@pytest.fixture
def db(monkeypatch, embedded):
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

    def fake_embed(texts: list[str]) -> list[list[float]]:
        embedded.extend(texts)
        return [[0.1] * DIM for _ in texts]

    monkeypatch.setattr(indexing_service, "embed_texts", fake_embed)

    with Session(engine) as session:
        session.execute(text(vec_chunks_ddl(DIM)))
        session.execute(text(CHUNK_FTS_DDL))
        session.add(
            Document(
                document_id="doc-a",
                url="https://example.com/a",
                title=TITLE,
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
    assert chunk_count(db) == expected_chunks(250)


def test_a_larger_chunk_size_makes_fewer_chunks(db):
    save_index_state(DIM, "gemini:gemini-embedding-001", 500, db)

    run_indexing_batch(db)

    assert chunk_count(db) == expected_chunks(500)


def test_the_fts_rows_follow_the_same_split(db):
    """전문 색인이 청크와 짝이 맞지 않으면 검색이 없는 청크를 가리킨다."""
    save_index_state(DIM, "gemini:gemini-embedding-001", 250, db)

    run_indexing_batch(db)

    fts_rows = db.execute(text("SELECT count(*) FROM chunk_fts")).scalar_one()
    vectors = db.execute(text("SELECT count(*) FROM vec_chunks")).scalar_one()
    assert fts_rows == chunk_count(db)
    assert vectors == chunk_count(db)


def test_the_fts_rows_carry_the_document_title(db):
    """제목으로도 키워드 검색이 걸리도록 전문 색인에 제목을 함께 넣는다."""
    save_index_state(DIM, "gemini:gemini-embedding-001", 250, db)

    run_indexing_batch(db)

    assert db.execute(text("SELECT DISTINCT title FROM chunk_fts")).scalars().all() == [TITLE]


def test_the_fts_title_is_not_truncated(db):
    """임베딩 쪽 제목은 입력 한계 때문에 잘리지만, FTS 에는 그런 한계가 없다."""
    long_title = "제" * 500
    db.execute(text("UPDATE documents SET title = :title"), {"title": long_title})
    save_index_state(DIM, "gemini:gemini-embedding-001", 250, db)

    run_indexing_batch(db)

    assert db.execute(text("SELECT DISTINCT title FROM chunk_fts")).scalars().all() == [long_title]


def test_embedding_input_stays_within_the_chunk_size(db, embedded):
    """제목까지 합친 임베딩 입력이 한계를 넘으면 넘친 뒷부분이 오류 없이 버려진다."""
    save_index_state(DIM, "gemini:gemini-embedding-001", 250, db)

    run_indexing_batch(db)

    assert embedded
    assert max(len(text_) for text_ in embedded) <= 250


def test_a_longer_title_leaves_less_room_for_the_body(db, embedded):
    """제목이 길어지면 그만큼 청크가 짧아진다 — 한계는 제목과 본문이 나눠 쓴다."""
    db.execute(text("UPDATE documents SET title = :title"), {"title": "제" * 40})
    save_index_state(DIM, "gemini:gemini-embedding-001", 250, db)

    run_indexing_batch(db)

    assert chunk_count(db) == expected_chunks(250, title="제" * 40)
    assert max(len(text_) for text_ in embedded) <= 250


def test_an_overlong_title_is_truncated_instead_of_starving_the_body(db, embedded):
    """제목이 한계보다 길어도 청크가 1자씩 쪼개지지 않는다."""
    db.execute(text("UPDATE documents SET title = :title"), {"title": "제" * 500})
    save_index_state(DIM, "gemini:gemini-embedding-001", 250, db)

    run_indexing_batch(db)

    body_share = 1 - MAX_TITLE_SHARE
    assert chunk_count(db) <= -(-BODY_CHARS // int(250 * body_share)) + 1
    assert max(len(text_) for text_ in embedded) <= 250


def test_budget_split_reserves_room_for_the_title_and_newline():
    title, chunk_chars = split_embedding_budget("제목", 100)
    assert title == "제목"
    assert chunk_chars == 100 - len("제목") - 1

    # 제목이 없으면 개행 한 자만 빠진다.
    assert split_embedding_budget("", 100) == ("", 99)
