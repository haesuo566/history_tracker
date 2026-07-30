from sqlalchemy import text

from backend.core.config import settings
from backend.db.base import Base
from backend.db.session import engine, is_sqlite
from backend.models import chunk, document  # noqa: F401 registers ORM tables on Base.metadata

VEC_CHUNKS_DDL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    document_id TEXT PARTITION KEY,
    seq INTEGER,
    embedding FLOAT[{settings.embedding_dim}]
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
