import sqlite_vec
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.document import Document
from backend.schemas.chat import ChatResult
from backend.services.embedding import embed_query
from backend.services.query_parser import rewrite_query
from backend.services.tokenizer import extract_nouns

RRF_K = 60
MAX_COSINE_DISTANCE = 1 - settings.min_cosine_similarity

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


def search_history(query: str, db: Session, limit: int = 50) -> ChatResult | None:
    """query와 가장 유사한 검색 기록(문서)을 벡터/FTS 검색 후 RRF로 병합해 1위 문서를 반환한다."""
    parsed_query = rewrite_query(query)
    logger.debug("search query rewritten: {!r} -> {!r}", query, parsed_query)

    # 벡터 검색: 코사인 거리 기준 최근접 k개 중 MAX_COSINE_DISTANCE(유사도 하한) 이내만 SQL에서 필터링
    query_embedding = embed_query(parsed_query)
    vector_hits = db.execute(
        VECTOR_SEARCH_SQL,
        {
            "embedding": sqlite_vec.serialize_float32(query_embedding),
            "limit": limit,
            "max_distance": MAX_COSINE_DISTANCE,
        },
    ).all()
    vector_keys: list[ChunkKey] = [(document_id, seq) for document_id, seq, _distance in vector_hits]

    # FTS 검색: query에서 추출한 명사를 OR로 묶어 매칭, 명사 중 실제 본문에 등장한 개수가
    # required_matches(최소 매칭 단어 수) 미만인 결과는 약한 매칭으로 보고 제외
    nouns = extract_nouns(parsed_query)
    fts_keys: list[ChunkKey] = []
    if nouns:
        fts_query = " OR ".join(nouns)
        fts_hits = db.execute(FTS_SEARCH_SQL, {"query": fts_query, "limit": limit}).all()
        required_matches = min(settings.min_fts_matched_terms, len(nouns))
        for vector_key, _rank, body in fts_hits:
            matched_terms = sum(1 for noun in nouns if noun.lower() in body.lower())
            if matched_terms < required_matches:
                continue
            document_id, seq = vector_key.rsplit(":", 1)
            fts_keys.append((document_id, int(seq)))

    # 벡터/FTS 순위 목록을 RRF로 병합한 뒤, 청크 점수를 문서 단위로 집계(청크 중 최고 점수를 문서 점수로 사용)
    chunk_scores = _rrf_merge(vector_keys, fts_keys)

    document_scores: dict[str, float] = {}
    for (document_id, _seq), score in chunk_scores.items():
        document_scores[document_id] = max(document_scores.get(document_id, 0.0), score)

    if not document_scores:
        logger.info("search found no match: query={!r} vector_hits={} fts_hits={}", query, len(vector_keys), len(fts_keys))
        return None

    # 최고 점수 문서를 조회해 결과로 반환
    top_document_id = max(document_scores, key=lambda document_id: document_scores[document_id])
    document = db.scalar(select(Document).where(Document.document_id == top_document_id))
    if document is None:
        logger.warning("search matched document_id={} but it no longer exists", top_document_id)
        return None

    logger.info(
        "search matched: query={!r} document_id={} score={:.4f}",
        query,
        top_document_id,
        document_scores[top_document_id],
    )

    return ChatResult(
        document_id=top_document_id,
        url=document.url,
        title=document.title,
        score=document_scores[top_document_id],
    )
