from loguru import logger
from sqlalchemy import bindparam, text

from backend.core.config import settings
from backend.db.base import Base
from backend.db.session import engine, is_sqlite

# ORM 테이블 등록용
from backend.models import app_setting, chunk, conversation, document  # noqa: F401
from backend.models.conversation import TITLE_MAX_CHARS
from backend.services.document import document_hash


def vec_chunks_ddl(dim: int) -> str:
    """vec_chunks 생성문. 차원은 그때 쓰는 임베딩이 정하므로 인자로 받는다.

    가상 테이블은 차원을 바꾸는 ALTER가 없어, 임베딩을 바꾸면 테이블을 지우고 다시 만들어야
    한다(services.reindex).
    """
    return f"""
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    document_id TEXT PARTITION KEY,
    seq INTEGER,
    embedding FLOAT[{dim}] distance_metric=cosine
)
"""


# title 을 body 와 나눠 두는 것은 둘을 구별해 가중치를 줄 수 있게 하려는 것이다. 한 열에 합치면
# 제목이 그 문서의 모든 청크 행에 반복 색인되어 제목 단어의 IDF 가 희석되기도 한다.
CHUNK_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    vector_key UNINDEXED,
    title,
    body
)
"""


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if is_sqlite:
        with engine.begin() as conn:
            conn.execute(text(vec_chunks_ddl(_indexed_dim(conn))))
            conn.execute(text(CHUNK_FTS_DDL))
            _ensure_chunk_fts_columns(conn)
            _ensure_column(conn, "conversations", "title", f"VARCHAR({TITLE_MAX_CHARS + 1})")
            _ensure_column(conn, "messages", "result_document_ids", "JSON")
            _migrate_document_hash_to_url(conn)


def _indexed_dim(conn) -> int:
    """지금 색인이 쓰는 차원. 재색인이 app_settings에 남긴 값이 있으면 그것을 쓴다.

    services.runtime_settings 를 거치지 않고 직접 읽는다. 그쪽은 자체 세션(SessionLocal)을 여는데,
    여기는 테이블을 만드는 중인 트랜잭션 안이라 같은 커넥션으로 읽어야 한다.

    값이 없으면 EMBEDDING_DIM이다 — 재색인 기능이 없던 시절에 만들어진 색인은 모두 그 차원이다.
    """
    row = conn.execute(
        text("SELECT value FROM app_settings WHERE key = 'indexed_embedding_dim'")
    ).scalar_one_or_none()
    if row is None:
        return settings.embedding_dim
    try:
        return int(row)
    except ValueError:
        return settings.embedding_dim


def _ensure_chunk_fts_columns(conn) -> None:
    """chunk_fts 의 열이 지금 DDL 과 다르면 지우고 다시 만든다.

    가상 테이블에는 열을 더하는 ALTER 가 없어 `_ensure_column` 방식을 쓸 수 없다. 전문 색인은
    청크 본문의 사본이라 본문만 있으면 다시 만들 수 있는 데이터이므로 버려도 잃는 것이 없지만,
    **다시 채우는 것은 재색인(`POST /reindex` → `POST /batch`)이다.** 이미 `checked = true` 인
    문서는 배치가 건너뛰므로 재색인 없이는 채워지지 않는다.

    그때까지 전문 검색은 빈 테이블을 보고 벡터 검색만 결과를 낸다 — 검색이 아예 실패하는 것보다는
    낫다는 판단으로, `services.search._vector_search_if_usable` 이 반대 상황에서 하는 것과 같다.
    """
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(chunk_fts)")).all()}
    if not columns or "title" in columns:
        return

    logger.warning(
        "chunk_fts has no title column — recreating it. Full-text search stays empty until "
        "POST /reindex then POST /batch."
    )
    conn.execute(text("DROP TABLE chunk_fts"))
    conn.execute(text(CHUNK_FTS_DDL))


HASH_SCHEME_KEY = "documents_hash_scheme"
HASH_SCHEME_URL = "url"


def _migrate_document_hash_to_url(conn) -> None:
    """documents.hash 를 sha256(url) 로 다시 계산한다 (services.document.document_hash 참고).

    옛 방식은 sha256(url + content) 였다. 이미 쌓인 행은 그 해시를 그대로 들고 있어서, 그냥
    두면 같은 URL 이 새 방식으로 한 번 더 들어온다. hash 에 unique 제약이 걸려 있으므로 재계산
    전에 URL 중복을 먼저 정리해야 한다 — **가장 오래된 행만 남긴다.** 앞으로 들어오는 재방문분을
    무시하는 것과 같은 규칙이다(먼저 수집된 본문이 남는다).

    지워지는 문서의 청크·벡터·전문 색인도 함께 버린다. 남겨두면 검색이 없는 문서를 가리킨다.

    documents 전체를 훑으므로 끝나면 app_settings 에 표시를 남겨 다음 기동부터는 건너뛴다.
    """
    scheme = conn.execute(
        text("SELECT value FROM app_settings WHERE key = :key"), {"key": HASH_SCHEME_KEY}
    ).scalar_one_or_none()
    if scheme == HASH_SCHEME_URL:
        return

    duplicates = conn.execute(
        text(
            """
            SELECT document_id FROM documents
            WHERE id NOT IN (SELECT MIN(id) FROM documents GROUP BY url)
            """
        )
    ).scalars().all()

    for document_id in duplicates:
        conn.execute(
            text("DELETE FROM chunks WHERE document_id = :id"), {"id": document_id}
        )
        conn.execute(
            text("DELETE FROM vec_chunks WHERE document_id = :id"), {"id": document_id}
        )
        conn.execute(
            text("DELETE FROM chunk_fts WHERE vector_key LIKE :prefix"),
            {"prefix": f"{document_id}:%"},
        )
    if duplicates:
        conn.execute(
            text("DELETE FROM documents WHERE document_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": list(duplicates)},
        )

    rows = conn.execute(text("SELECT id, url FROM documents")).all()
    for row_id, url in rows:
        conn.execute(
            text("UPDATE documents SET hash = :hash WHERE id = :id"),
            {"hash": document_hash(url), "id": row_id},
        )

    conn.execute(
        text("INSERT OR REPLACE INTO app_settings (key, value) VALUES (:key, :value)"),
        {"key": HASH_SCHEME_KEY, "value": HASH_SCHEME_URL},
    )
    logger.info(
        "documents.hash migrated to sha256(url): {} row(s), {} duplicate(s) removed",
        len(rows),
        len(duplicates),
    )


def _ensure_column(conn, table: str, column: str, ddl_type: str) -> None:
    """create_all은 이미 있는 테이블에 새 컬럼을 더해주지 않는다.

    마이그레이션 도구가 없는 상태에서 컬럼을 뒤늦게 추가한 자리들이다. 기존 app.db에는 문서·임베딩
    처럼 다시 만들 수 없거나 비용이 드는 데이터가 있어 통째로 지우고 새로 만들 수 없으므로, 컬럼이
    없을 때만 ALTER TABLE로 더한다.
    """
    columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}
    if column not in columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
