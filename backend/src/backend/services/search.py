import sqlite_vec
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.schemas.chat import ChatResult
from backend.services.embedding import embed_query
from backend.services.query_parser import rewrite_query
from backend.services.tokenizer import extract_nouns

RRF_K = 60
MAX_COSINE_DISTANCE = 1 - settings.min_cosine_similarity
DEFAULT_RESULT_COUNT = 5

VECTOR_SEARCH_SQL = text(
    "SELECT document_id, seq, distance FROM vec_chunks "
    "WHERE embedding MATCH :embedding AND k = :limit AND distance <= :max_distance ORDER BY distance"
)
FTS_SEARCH_SQL = text(
    "SELECT vector_key, rank, body FROM chunk_fts WHERE chunk_fts MATCH :query ORDER BY rank LIMIT :limit"
)

type ChunkKey = tuple[str, int]


def _rrf_merge(*ranked_lists: list[ChunkKey]) -> dict[ChunkKey, float]:
    """각 순위 목록에 대해 1/(RRF_K + rank)를 계산해 청크별로 합산한다."""
    scores: dict[ChunkKey, float] = {}
    for ranked_keys in ranked_lists:
        for rank, key in enumerate(ranked_keys, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def _vector_search(db: Session, query_embedding: list[float], limit: int) -> list[ChunkKey]:
    """코사인 거리 기준 최근접 limit개 중 MAX_COSINE_DISTANCE(유사도 하한) 이내만 SQL에서 필터링해 반환한다."""
    vector_hits = db.execute(
        VECTOR_SEARCH_SQL,
        {
            "embedding": sqlite_vec.serialize_float32(query_embedding),
            "limit": limit,
            "max_distance": MAX_COSINE_DISTANCE,
        },
    ).all()
    return [(document_id, seq) for document_id, seq, _distance in vector_hits]


def _fts_search(db: Session, nouns: list[str], limit: int) -> list[ChunkKey]:
    """명사를 OR로 묶어 매칭하고, 명사 중 실제 본문에 등장한 개수가 required_matches(최소 매칭 단어 수)
    미만인 결과는 약한 매칭으로 보고 제외한다."""
    if not nouns:
        return []

    fts_query = " OR ".join(nouns)
    fts_hits = db.execute(FTS_SEARCH_SQL, {"query": fts_query, "limit": limit}).all()
    required_matches = min(settings.min_fts_matched_terms, len(nouns))

    fts_keys: list[ChunkKey] = []
    for vector_key, _rank, body in fts_hits:
        matched_terms = sum(1 for noun in nouns if noun.lower() in body.lower())
        if matched_terms < required_matches:
            continue
        document_id, seq = vector_key.rsplit(":", 1)
        fts_keys.append((document_id, int(seq)))
    return fts_keys


def _merge_document_scores(vector_keys: list[ChunkKey], fts_keys: list[ChunkKey]) -> dict[str, tuple[float, int]]:
    """벡터/FTS 순위 목록을 RRF로 병합한 뒤, 문서 단위로 최고 점수와 그 점수를 낸 청크의 seq를 집계한다."""
    chunk_scores = _rrf_merge(vector_keys, fts_keys)
    document_best: dict[str, tuple[float, int]] = {}
    for (document_id, seq), score in chunk_scores.items():
        best = document_best.get(document_id)
        if best is None or score > best[0]:
            document_best[document_id] = (score, seq)
    return document_best


def _fetch_top_results(db: Session, document_best: dict[str, tuple[float, int]], count: int) -> list[ChatResult]:
    """점수 상위 count개 문서를 조회해, 최고 점수를 낸 청크 구간으로 본문을 잘라 ChatResult 리스트로 반환한다."""
    top_document_ids = sorted(document_best, key=lambda document_id: document_best[document_id][0], reverse=True)[
        :count
    ]
    documents_by_id = {
        document.document_id: document
        for document in db.scalars(select(Document).where(Document.document_id.in_(top_document_ids)))
    }
    chunks_by_key = {
        (chunk.document_id, chunk.seq): chunk
        for chunk in db.scalars(select(Chunk).where(Chunk.document_id.in_(top_document_ids)))
    }

    results = []
    for document_id in top_document_ids:
        document = documents_by_id.get(document_id)
        if document is None:
            logger.warning("search matched document_id={} but it no longer exists", document_id)
            continue
        score, seq = document_best[document_id]
        chunk = chunks_by_key.get((document_id, seq))
        snippet = document.full_text[chunk.char_start : chunk.char_end] if chunk else ""
        results.append(
            ChatResult(
                document_id=document_id,
                url=document.url,
                title=document.title,
                score=score,
                snippet=snippet,
            )
        )
    return results


def search_history(query: str, db: Session, limit: int = 50) -> list[ChatResult]:
    """query와 가장 유사한 검색 기록(문서)을 벡터/FTS 검색 후 RRF로 병합해 상위 count개 문서를 반환한다."""
    parsed = rewrite_query(query)
    logger.debug("search query rewritten: {!r} -> {!r}", query, parsed.query)
    count = parsed.desired_count if parsed.desired_count and parsed.desired_count > 0 else DEFAULT_RESULT_COUNT

    query_embedding = embed_query(parsed.query)
    vector_keys = _vector_search(db, query_embedding, limit)

    nouns = extract_nouns(parsed.query)
    fts_keys = _fts_search(db, nouns, limit)

    document_best = _merge_document_scores(vector_keys, fts_keys)
    if not document_best:
        logger.info("search found no match: query={!r} vector_hits={} fts_hits={}", query, len(vector_keys), len(fts_keys))
        return []

    results = _fetch_top_results(db, document_best, count)
    logger.info(
        "search matched {} document(s): query={!r} top_score={:.4f}",
        len(results),
        query,
        max(score for score, _seq in document_best.values()),
    )
    return results
