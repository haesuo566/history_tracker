import hashlib

import pytest
import sqlite_vec
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

from backend.db.base import Base
from backend.db.init_db import (
    CHUNK_FTS_DDL,
    HASH_SCHEME_KEY,
    HASH_SCHEME_URL,
    _ensure_chunk_fts_columns,
    _migrate_document_hash_to_url,
    vec_chunks_ddl,
)
from backend.models.app_setting import AppSetting
from backend.models.chunk import Chunk
from backend.models.document import Document

DIM = 4


def legacy_hash(url: str, content: str) -> str:
    """content 를 섞던 옛 방식. 이미 쌓인 app.db 의 행들이 들고 있는 해시다."""
    return hashlib.sha256(f"{url}\n{content}".encode()).hexdigest()


@pytest.fixture
def conn():
    """vec_chunks·chunk_fts 까지 갖춘 인메모리 DB 커넥션."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _load_sqlite_vec(dbapi_connection, connection_record) -> None:
        dbapi_connection.enable_load_extension(True)
        sqlite_vec.load(dbapi_connection)
        dbapi_connection.enable_load_extension(False)

    Base.metadata.create_all(
        bind=engine, tables=[Document.__table__, Chunk.__table__, AppSetting.__table__]
    )
    with engine.begin() as connection:
        connection.execute(text(vec_chunks_ddl(DIM)))
        connection.execute(text(CHUNK_FTS_DDL))
        yield connection


def insert_document(conn, document_id: str, url: str, content: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO documents (document_id, url, title, full_text, hash, timestamp, checked)
            VALUES (:document_id, :url, 't', :full_text, :hash, '2026-08-01 00:00:00', 1)
            """
        ),
        {
            "document_id": document_id,
            "url": url,
            "full_text": content,
            "hash": legacy_hash(url, content),
        },
    )
    conn.execute(
        text(
            "INSERT INTO chunks (document_id, seq, char_start, char_end) "
            "VALUES (:document_id, 0, 0, 10)"
        ),
        {"document_id": document_id},
    )
    conn.execute(
        text("INSERT INTO vec_chunks (document_id, seq, embedding) VALUES (:id, 0, :embedding)"),
        {"id": document_id, "embedding": sqlite_vec.serialize_float32([0.1] * DIM)},
    )
    conn.execute(
        text("INSERT INTO chunk_fts (vector_key, body) VALUES (:key, 'body')"),
        {"key": f"{document_id}:0"},
    )


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def test_duplicate_urls_collapse_to_oldest_row(conn):
    """본문이 조금씩 다른 같은 URL 3건 -> 먼저 들어온 한 건만 남는다."""
    insert_document(conn, "doc-1", "https://a.test/1", "조회수 1")
    insert_document(conn, "doc-2", "https://a.test/1", "조회수 2")
    insert_document(conn, "doc-3", "https://a.test/1", "조회수 3")
    insert_document(conn, "doc-4", "https://b.test/2", "다른 페이지")

    _migrate_document_hash_to_url(conn)

    rows = conn.execute(
        text("SELECT document_id, url, full_text, hash FROM documents ORDER BY id")
    ).all()
    assert [(r.document_id, r.full_text) for r in rows] == [
        ("doc-1", "조회수 1"),
        ("doc-4", "다른 페이지"),
    ]
    assert [r.hash for r in rows] == [url_hash("https://a.test/1"), url_hash("https://b.test/2")]


def test_index_of_removed_documents_is_dropped(conn):
    insert_document(conn, "doc-1", "https://a.test/1", "처음")
    insert_document(conn, "doc-2", "https://a.test/1", "나중")

    _migrate_document_hash_to_url(conn)

    assert conn.execute(text("SELECT document_id FROM chunks")).scalars().all() == ["doc-1"]
    assert conn.execute(text("SELECT document_id FROM vec_chunks")).scalars().all() == ["doc-1"]
    assert conn.execute(text("SELECT vector_key FROM chunk_fts")).scalars().all() == ["doc-1:0"]


def test_migration_runs_once(conn):
    """표시를 남긴 뒤로는 건너뛴다 — 매 기동마다 documents 전체를 훑지 않게."""
    insert_document(conn, "doc-1", "https://a.test/1", "처음")
    _migrate_document_hash_to_url(conn)

    assert (
        conn.execute(
            text("SELECT value FROM app_settings WHERE key = :key"), {"key": HASH_SCHEME_KEY}
        ).scalar_one()
        == HASH_SCHEME_URL
    )

    # 표시가 있는 상태에서 옛 해시 행을 밀어넣어도 손대지 않는다.
    insert_document(conn, "doc-2", "https://c.test/3", "본문")
    _migrate_document_hash_to_url(conn)

    assert conn.execute(
        text("SELECT hash FROM documents WHERE document_id = 'doc-2'")
    ).scalar_one() == legacy_hash("https://c.test/3", "본문")


def test_chunk_fts_without_title_is_recreated(conn):
    """가상 테이블에는 열을 더하는 ALTER 가 없어 지우고 다시 만든다. 내용은 재색인이 채운다."""
    conn.execute(text("DROP TABLE chunk_fts"))
    conn.execute(text("CREATE VIRTUAL TABLE chunk_fts USING fts5(vector_key UNINDEXED, body)"))
    conn.execute(text("INSERT INTO chunk_fts (vector_key, body) VALUES ('doc-a:0', '본문')"))

    _ensure_chunk_fts_columns(conn)

    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(chunk_fts)")).all()}
    assert columns == {"vector_key", "title", "body"}
    assert conn.execute(text("SELECT count(*) FROM chunk_fts")).scalar_one() == 0


def test_chunk_fts_with_title_is_left_alone(conn):
    conn.execute(
        text("INSERT INTO chunk_fts (vector_key, title, body) VALUES ('doc-a:0', '제목', '본문')")
    )

    _ensure_chunk_fts_columns(conn)

    assert conn.execute(text("SELECT count(*) FROM chunk_fts")).scalar_one() == 1


def test_no_duplicates_only_rewrites_hash(conn):
    insert_document(conn, "doc-1", "https://a.test/1", "본문")

    _migrate_document_hash_to_url(conn)

    assert conn.execute(text("SELECT hash FROM documents")).scalar_one() == url_hash(
        "https://a.test/1"
    )
    assert conn.execute(text("SELECT COUNT(*) FROM documents")).scalar_one() == 1
