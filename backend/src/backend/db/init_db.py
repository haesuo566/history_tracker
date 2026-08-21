from sqlalchemy import text

from backend.core.config import settings
from backend.db.base import Base
from backend.db.session import engine, is_sqlite

# ORM 테이블 등록용
from backend.models import app_setting, chunk, conversation, document  # noqa: F401
from backend.models.conversation import TITLE_MAX_CHARS


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


CHUNK_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    vector_key UNINDEXED,
    body
)
"""


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if is_sqlite:
        with engine.begin() as conn:
            conn.execute(text(vec_chunks_ddl(_indexed_dim(conn))))
            conn.execute(text(CHUNK_FTS_DDL))
            _ensure_column(conn, "conversations", "title", f"VARCHAR({TITLE_MAX_CHARS + 1})")
            _ensure_column(conn, "messages", "result_document_ids", "JSON")


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


def _ensure_column(conn, table: str, column: str, ddl_type: str) -> None:
    """create_all은 이미 있는 테이블에 새 컬럼을 더해주지 않는다.

    마이그레이션 도구가 없는 상태에서 컬럼을 뒤늦게 추가한 자리들이다. 기존 app.db에는 문서·임베딩
    처럼 다시 만들 수 없거나 비용이 드는 데이터가 있어 통째로 지우고 새로 만들 수 없으므로, 컬럼이
    없을 때만 ALTER TABLE로 더한다.
    """
    columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}
    if column not in columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
