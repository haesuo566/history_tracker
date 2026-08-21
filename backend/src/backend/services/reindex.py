"""색인을 비우고 지금 설정된 임베딩으로 다시 쌓을 준비를 한다.

임베딩 제공자나 모델을 바꾸면 이미 쌓인 벡터는 다른 공간의 좌표가 되어 검색에 쓸 수 없다. 차원까지
달라지면 vec_chunks 자체를 그 차원으로 다시 만들어야 한다(가상 테이블에는 차원을 바꾸는 ALTER가
없다).

문서 본문(documents)은 건드리지 않는다. 수집은 확장이 방문할 때만 일어나 다시 만들 수 없는
데이터이고, 청크·벡터·전문 색인은 본문만 있으면 언제든 다시 만들 수 있다.
"""

from loguru import logger
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.db.init_db import CHUNK_FTS_DDL, vec_chunks_ddl
from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.schemas.reindex import ReindexResponse
from backend.services.embedding import detect_chunk_chars, detect_dim
from backend.services.runtime_settings import get_settings, save_index_state


def reset_index(db: Session) -> ReindexResponse:
    """청크·벡터·전문 색인을 버리고 모든 문서를 색인 대기로 되돌린다.

    되돌릴 수 없다. 실제로 다시 쌓는 것은 POST /batch 다.
    """
    current = get_settings()

    # 차원과 청크 크기를 먼저 알아낸다. TEI가 죽어 있으면 여기서 실패하는데, 그 편이 색인을 다
    # 지운 뒤에 실패하는 것보다 낫다 — 되돌릴 수 없는 일을 하기 전에 막아야 한다.
    dim = detect_dim(current)
    chunk_chars = detect_chunk_chars(current)
    recreated = dim != current.indexed_dim

    logger.info(
        "reindex starting: provider={} signature={!r} dim={} (was {}) chunk={} chars (was {}) recreate={}",
        current.embedding_provider.value,
        current.embedding_signature,
        dim,
        current.indexed_dim,
        chunk_chars,
        current.indexed_chunk_chars,
        recreated,
    )

    if recreated:
        # 차원이 다르면 테이블을 다시 만들어야 한다. DELETE로는 선언된 차원이 남는다.
        db.execute(text("DROP TABLE IF EXISTS vec_chunks"))
        db.execute(text(vec_chunks_ddl(dim)))
    else:
        db.execute(text("DELETE FROM vec_chunks"))

    # 전문 색인은 차원과 무관하지만 청크 경계가 달라질 수 있어 함께 비운다. 청크가 사라진 뒤에도
    # 남아 있으면 검색이 없는 청크를 가리킨다.
    db.execute(text("DROP TABLE IF EXISTS chunk_fts"))
    db.execute(text(CHUNK_FTS_DDL))

    db.query(Chunk).delete()
    pending = db.scalar(select(func.count()).select_from(Document)) or 0
    db.query(Document).update({Document.checked: False})

    # 이 호출이 커밋까지 한다. 색인을 비운 것과 그 사실의 기록이 한 트랜잭션에 들어가야, 중간에
    # 끊겨서 '비어 있는데 예전 서명이 남은' 상태가 생기지 않는다.
    save_index_state(dim, current.embedding_signature, chunk_chars, db)

    logger.info(
        "reindex ready: {} document(s) pending, dim={} chunk={} chars", pending, dim, chunk_chars
    )
    return ReindexResponse(
        provider=current.embedding_provider.value,
        dim=dim,
        chunk_chars=chunk_chars,
        pending=pending,
        recreated=recreated,
    )
