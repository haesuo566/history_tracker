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
INSERT_CHUNK_FTS = text(
    "INSERT INTO chunk_fts (vector_key, title, body) VALUES (:vector_key, :title, :body)"
)

# 제목이 청크 예산에서 가져갈 수 있는 최대 비율. 제목이 비정상적으로 긴 문서에서 본문 몫이
# 거의 남지 않아 청크가 잘게 쪼개지는 것을 막는다. 넘치는 제목은 잘라서 임베딩한다.
MAX_TITLE_SHARE = 0.25


def split_embedding_budget(title: str, max_chars: int) -> tuple[str, int]:
    """임베딩에 쓸 제목과, 청크에 남는 문자 수를 정한다.

    임베딩에 넣는 문자열은 `f"{title}\\n{chunk.text}"` 다. 청크를 `max_chars` 까지 꽉 채워
    자르면 제목과 개행만큼 한계를 넘고, 넘친 뒷부분은 오류 없이 버려진다(Gemini도 TEI도
    그렇다). `max_chars` 자체가 토큰 한계에서 최악의 문자/토큰 비율로 환산된 값이라 여유가
    거의 없으므로(core.model_catalog.CHARS_PER_TOKEN), 제목이 쓸 자리를 미리 빼둔다.
    """
    kept_title = title[: max(0, int(max_chars * MAX_TITLE_SHARE))]
    return kept_title, max(1, max_chars - len(kept_title) - 1)  # 개행 한 자


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
                title, chunk_chars = split_embedding_budget(document.title, max_chars)
                chunks = chunk_text(document.full_text, max_chars=chunk_chars)
                document.checked = True

                if chunks:
                    embeddings = embed_texts([f"{title}\n{chunk.text}" for chunk in chunks])
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
                                # 전문 색인에는 자르지 않은 제목이 들어간다. 길이를 줄이는 것은
                                # 임베딩 입력 한계 때문이고, FTS 에는 그런 한계가 없다.
                                "title": document.title,
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
