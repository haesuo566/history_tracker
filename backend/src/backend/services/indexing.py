import sqlite_vec
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.schemas.batch import BatchResponse
from backend.services.chunking import chunk_text
from backend.services.embedding import embed_texts
from backend.services.runtime_settings import get_settings

INSERT_VEC_CHUNK = text(
    "INSERT INTO vec_chunks (document_id, seq, embedding) VALUES (:document_id, :seq, :embedding)"
)
INSERT_CHUNK_FTS = text("INSERT INTO chunk_fts (vector_key, body) VALUES (:vector_key, :body)")


def run_indexing_batch(db: Session) -> BatchResponse:
    """checked=False인 문서를 청킹/임베딩해 인덱싱하고 결과 통계를 반환한다."""
    documents = db.scalars(select(Document).where(Document.checked.is_(False))).all()

    # 청크 크기는 색인 상태에 기록된 값을 쓴다. 매 배치에서 임베딩 서버에 다시 물으면, 그 사이
    # 값이 달라졌을 때 같은 색인 안에 경계가 다른 청크가 섞인다. 값을 정하는 것은 재색인이다.
    max_chars = get_settings().indexed_chunk_chars
    logger.info(
        "indexing batch started: {} document(s) pending, chunk={} chars", len(documents), max_chars
    )

    succeeded = 0
    failed = 0

    for document in documents:
        try:
            with db.begin_nested():
                chunks = chunk_text(document.full_text, max_chars=max_chars)
                document.checked = True

                if chunks:
                    embeddings = embed_texts([f"{document.title}\n{chunk.text}" for chunk in chunks])
                    for seq, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                        db.add(
                            Chunk(
                                document_id=document.document_id,
                                seq=seq,
                                char_start=chunk.char_start,
                                char_end=chunk.char_end,
                            )
                        )
                        db.execute(
                            INSERT_VEC_CHUNK,
                            {
                                "document_id": document.document_id,
                                "seq": seq,
                                "embedding": sqlite_vec.serialize_float32(embedding),
                            },
                        )
                        db.execute(
                            INSERT_CHUNK_FTS,
                            {
                                "vector_key": f"{document.document_id}:{seq}",
                                "body": chunk.text,
                            },
                        )
        except Exception:
            failed += 1
            logger.exception("indexing failed: document_id={} url={}", document.document_id, document.url)
        else:
            succeeded += 1

    db.commit()

    logger.info("indexing batch finished: attempted={} succeeded={} failed={}", len(documents), succeeded, failed)

    return BatchResponse(attempted=len(documents), succeeded=succeeded, failed=failed)
