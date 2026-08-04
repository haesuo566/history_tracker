from sqlalchemy import text

from backend.core.config import settings
from backend.db.base import Base
from backend.db.session import engine, is_sqlite
from backend.models import chunk, conversation, document  # noqa: F401 ORM 테이블 등록용
from backend.models.conversation import TITLE_MAX_CHARS

VEC_CHUNKS_DDL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    document_id TEXT PARTITION KEY,
    seq INTEGER,
    embedding FLOAT[{settings.embedding_dim}] distance_metric=cosine
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
            conn.execute(text(VEC_CHUNKS_DDL))
            conn.execute(text(CHUNK_FTS_DDL))
            _ensure_conversations_title_column(conn)


def _ensure_conversations_title_column(conn) -> None:
    """create_all은 이미 있는 테이블에 새 컬럼을 더해주지 않는다.

    마이그레이션 도구가 없는 상태에서 title을 뒤늦게 추가했다. 기존 app.db에는 문서·임베딩처럼
    다시 만들 수 없거나 비용이 드는 데이터가 있어 통째로 지우고 새로 만들 수 없으므로, 컬럼이
    없을 때만 ALTER TABLE로 더한다.
    """
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(conversations)")).all()}
    if "title" not in columns:
        conn.execute(text(f"ALTER TABLE conversations ADD COLUMN title VARCHAR({TITLE_MAX_CHARS + 1})"))
