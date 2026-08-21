import pytest
import sqlite_vec
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.core.config import settings
from backend.core.model_catalog import EmbeddingProvider
from backend.db.base import Base
from backend.db.init_db import CHUNK_FTS_DDL, vec_chunks_ddl
from backend.models.app_setting import AppSetting
from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.services import embedding as embedding_service
from backend.services import reindex as reindex_service
from backend.services.reindex import reset_index
from backend.services.runtime_settings import load_settings, reset_cache, save_settings

INDEXED_DIM = 4
TEI_URL = "http://tei.internal:8080"


@pytest.fixture
def db():
    """vec_chunks·chunk_fts 까지 갖춘 인메모리 DB. 문서 두 건과 그 색인이 들어 있다.

    sqlite-vec 확장을 실어야 vec0 가상 테이블을 만들 수 있어, 운영 엔진과 같은 방식으로 로드한다.
    """
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

    with Session(engine) as session:
        session.execute(text(vec_chunks_ddl(INDEXED_DIM)))
        session.execute(text(CHUNK_FTS_DDL))
        for index, document_id in enumerate(("doc-a", "doc-b")):
            session.add(
                Document(
                    document_id=document_id,
                    url=f"https://example.com/{document_id}",
                    title=document_id,
                    full_text="본문",
                    hash=f"hash-{document_id}",
                    checked=True,
                )
            )
            session.add(Chunk(document_id=document_id, seq=0, char_start=0, char_end=2))
            session.execute(
                text("INSERT INTO vec_chunks (document_id, seq, embedding) VALUES (:d, 0, :e)"),
                {"d": document_id, "e": sqlite_vec.serialize_float32([float(index)] * INDEXED_DIM)},
            )
            session.execute(
                text("INSERT INTO chunk_fts (vector_key, body) VALUES (:k, :b)"),
                {"k": f"{document_id}:0", "b": "본문"},
            )
        # 지금 색인이 4차원 Gemini 로 만들어져 있다고 기록해 둔다.
        session.add(AppSetting(key="indexed_embedding_dim", value=str(INDEXED_DIM)))
        session.add(AppSetting(key="indexed_embedding_signature", value="gemini:gemini-embedding-001"))
        session.commit()
        yield session

    reset_cache()


def counts(db: Session) -> dict[str, int]:
    def count(sql: str) -> int:
        return db.execute(text(sql)).scalar_one()

    return {
        "documents": count("SELECT count(*) FROM documents"),
        "chunks": count("SELECT count(*) FROM chunks"),
        "vectors": count("SELECT count(*) FROM vec_chunks"),
        "fts": count("SELECT count(*) FROM chunk_fts"),
        "pending": count("SELECT count(*) FROM documents WHERE checked = 0"),
    }


def use_tei(db: Session, monkeypatch, dim: int) -> None:
    """provider 를 TEI 로 돌리고, 그 서버가 dim 차원을 낸다고 해 둔다."""
    save_settings(
        {"embedding_provider": EmbeddingProvider.TEI.value, "tei_base_url": TEI_URL, "tei_model": "BAAI/bge-m3"},
        db,
    )
    monkeypatch.setattr(embedding_service, "detect_dim", lambda current=None: dim)
    monkeypatch.setattr(reindex_service, "detect_dim", lambda current=None: dim)


def test_documents_survive_a_reindex(db, monkeypatch):
    """수집은 확장이 방문할 때만 일어난다. 본문을 잃으면 다시 만들 방법이 없다."""
    use_tei(db, monkeypatch, dim=1024)

    reset_index(db)

    assert counts(db)["documents"] == 2


def test_the_index_is_emptied_and_documents_go_back_to_pending(db, monkeypatch):
    use_tei(db, monkeypatch, dim=1024)

    result = reset_index(db)

    after = counts(db)
    assert (after["chunks"], after["vectors"], after["fts"]) == (0, 0, 0)
    assert after["pending"] == 2
    assert result.pending == 2


def test_a_new_dimension_rebuilds_the_vector_table(db, monkeypatch):
    """가상 테이블은 차원을 바꾸는 ALTER 가 없다. DELETE 만 하면 선언된 차원이 그대로 남는다."""
    use_tei(db, monkeypatch, dim=1024)

    result = reset_index(db)

    assert result.recreated is True
    assert result.dim == 1024
    # 새 차원으로 실제로 넣을 수 있어야 한다. 예전 차원이 남아 있으면 여기서 실패한다.
    db.execute(
        text("INSERT INTO vec_chunks (document_id, seq, embedding) VALUES ('doc-a', 0, :e)"),
        {"e": sqlite_vec.serialize_float32([0.1] * 1024)},
    )


def test_the_same_dimension_keeps_the_table(db, monkeypatch):
    """모델만 바뀌고 차원이 같으면 테이블을 다시 만들 이유가 없다."""
    use_tei(db, monkeypatch, dim=INDEXED_DIM)

    result = reset_index(db)

    assert result.recreated is False
    assert counts(db)["vectors"] == 0


def test_the_new_signature_is_recorded(db, monkeypatch):
    """기록이 남지 않으면 재색인을 했는데도 검색이 계속 벡터를 건너뛴다."""
    use_tei(db, monkeypatch, dim=1024)

    reset_index(db)

    current = load_settings(db)
    assert current.indexed_dim == 1024
    assert current.indexed_signature == f"tei:{'BAAI/bge-m3'}"
    assert current.reindex_required is False


def test_a_provider_that_cannot_be_reached_leaves_the_index_alone(db, monkeypatch):
    """되돌릴 수 없는 일이다. 붙지도 못하는 상태에서 색인을 먼저 지워선 안 된다."""
    use_tei(db, monkeypatch, dim=1024)

    def explode(current=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(reindex_service, "detect_dim", explode)

    with pytest.raises(RuntimeError):
        reset_index(db)

    db.rollback()
    after = counts(db)
    assert (after["chunks"], after["vectors"], after["pending"]) == (2, 2, 0)


def test_gemini_reindex_uses_the_configured_dimension(db, monkeypatch):
    """Gemini 는 우리가 차원을 지정하므로 서버에 물어볼 것이 없다."""
    save_settings({"embedding_model": "gemini-embedding-2"}, db)

    result = reset_index(db)

    assert result.dim == settings.embedding_dim
    assert load_settings(db).indexed_signature == "gemini:gemini-embedding-2"
