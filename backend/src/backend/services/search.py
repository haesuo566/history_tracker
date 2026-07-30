import sqlite_vec
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.models.document import Document
from backend.schemas.chat import ChatResult
from backend.services.embedding import embed_query
from backend.services.query_parser import rewrite_query
from backend.services.tokenizer import extract_nouns

RRF_K = 60

VECTOR_SEARCH_SQL = text(
    "SELECT document_id, seq, distance FROM vec_chunks "
    "WHERE embedding MATCH :embedding AND k = :limit ORDER BY distance"
)
FTS_SEARCH_SQL = text(
    "SELECT vector_key, rank FROM chunk_fts WHERE chunk_fts MATCH :query ORDER BY rank LIMIT :limit"
)

type ChunkKey = tuple[str, int]


def _rrf_merge(*ranked_lists: list[ChunkKey]) -> dict[ChunkKey, float]:
    """각 순위 목록에 대해 1/(RRF_K + rank)를 계산해 청크별로 합산한다."""
    scores: dict[ChunkKey, float] = {}
    for ranked_keys in ranked_lists:
        for rank, key in enumerate(ranked_keys, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def search_history(query: str, db: Session, limit: int = 5) -> ChatResult | None:
    """query와 가장 유사한 검색 기록(문서)을 벡터/FTS 검색 후 RRF로 병합해 1위 문서를 반환한다."""
    parsed_query = rewrite_query(query)

    query_embedding = embed_query(parsed_query)
    vector_hits = db.execute(
        VECTOR_SEARCH_SQL,
        {"embedding": sqlite_vec.serialize_float32(query_embedding), "limit": limit},
    ).all()
    vector_keys: list[ChunkKey] = [(document_id, seq) for document_id, seq, _distance in vector_hits]

    nouns = extract_nouns(parsed_query)
    fts_keys: list[ChunkKey] = []
    if nouns:
        fts_query = " OR ".join(nouns)
        fts_hits = db.execute(FTS_SEARCH_SQL, {"query": fts_query, "limit": limit}).all()
        for vector_key, _rank in fts_hits:
            document_id, seq = vector_key.rsplit(":", 1)
            fts_keys.append((document_id, int(seq)))

    chunk_scores = _rrf_merge(vector_keys, fts_keys)

    document_scores: dict[str, float] = {}
    for (document_id, _seq), score in chunk_scores.items():
        document_scores[document_id] = max(document_scores.get(document_id, 0.0), score)

    if not document_scores:
        return None

    top_document_id = max(document_scores, key=lambda document_id: document_scores[document_id])
    document = db.scalar(select(Document).where(Document.document_id == top_document_id))
    if document is None:
        return None

    return ChatResult(
        document_id=top_document_id,
        url=document.url,
        title=document.title,
        score=document_scores[top_document_id],
    )
