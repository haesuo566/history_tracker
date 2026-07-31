import sqlite_vec
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.schemas.batch import BatchResponse
from backend.services.chunking import chunk_text
from backend.services.embedding import embed_texts

INSERT_VEC_CHUNK = text(
    "INSERT INTO vec_chunks (document_id, seq, embedding) VALUES (:document_id, :seq, :embedding)"
)
INSERT_CHUNK_FTS = text("INSERT INTO chunk_fts (vector_key, body) VALUES (:vector_key, :body)")


def run_indexing_batch(db: Session) -> BatchResponse:
    """checked=False인 문서를 청킹/임베딩해 인덱싱하고 결과 통계를 반환한다."""
    documents = db.scalars(select(Document).where(Document.checked.is_(False))).all()

    succeeded = 0
    failed = 0

    for document in documents:
        try:
            with db.begin_nested():
                chunks = chunk_text(document.full_text)
                document.checked = True

                if chunks:
                    embeddings = embed_texts([chunk.text for chunk in chunks])
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
        else:
            succeeded += 1

    db.commit()

    return BatchResponse(attempted=len(documents), succeeded=succeeded, failed=failed)
