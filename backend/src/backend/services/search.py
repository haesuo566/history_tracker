from datetime import datetime

import sqlite_vec
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.schemas.chat import ChatResult
from backend.services.detail import SNIPPET_CHARS
from backend.services.embedding import embed_query
from backend.services.runtime_settings import get_settings
from backend.services.timerange import TimeWindow
from backend.services.tokenizer import extract_nouns

RRF_K = 60
MAX_COSINE_DISTANCE = 1 - settings.min_cosine_similarity
DEFAULT_RESULT_COUNT = 5

# 기간만 말한 질의("어제 본 거 다 보여줘")에 몇 건까지 늘어놓을지. 검색 결과 기본값(5)보다 넉넉한
# 것은 이 갈래가 고르기가 아니라 훑어보기라서다.
LISTING_RESULT_COUNT = 10

# 기간이 걸리면 벡터 검색은 뽑아 온 뒤에야 거를 수 있다(vec0 가상 테이블이라 조인이 안 된다).
# 그 자리에서 기간 밖 청크가 얼마나 빠질지 알 수 없으므로 애초에 더 넉넉히 뽑는다.
FILTERED_VECTOR_LIMIT_FACTOR = 4

VECTOR_SEARCH_SQL = text(
    "SELECT document_id, seq, distance FROM vec_chunks "
    "WHERE embedding MATCH :embedding AND k = :limit AND distance <= :max_distance ORDER BY distance"
)
FTS_SEARCH_SQL = text(
    "SELECT vector_key, rank, title, body FROM chunk_fts "
    "WHERE chunk_fts MATCH :query ORDER BY rank LIMIT :limit"
)
# 전문 검색은 일반 테이블이라 documents를 조인할 수 있다. LIMIT 전에 기간을 걸어야 상위 50건이
# 기간 밖 문서로 채워져 정작 그 기간의 문서가 밀려나는 일이 없다. vector_key는 "{document_id}:{seq}"라
# 앞쪽을 잘라 문서를 찾는다. FTS 테이블에 별칭을 붙이지 않는 것은 MATCH 의 왼쪽이 테이블 이름이어야
# 하기 때문이다 — 별칭을 쓰면 "no such column" 이 된다.
FILTERED_FTS_SEARCH_SQL = text(
    "SELECT chunk_fts.vector_key, chunk_fts.rank, chunk_fts.title, chunk_fts.body FROM chunk_fts "
    "JOIN documents ON documents.document_id = "
    "substr(chunk_fts.vector_key, 1, instr(chunk_fts.vector_key, ':') - 1) "
    "WHERE chunk_fts MATCH :query "
    "AND documents.timestamp >= :since AND documents.timestamp < :until "
    "ORDER BY chunk_fts.rank LIMIT :limit"
)

type ChunkKey = tuple[str, int]

# SQLAlchemy 가 DateTime 컬럼을 SQLite 에 적어 넣는 형식. 아래 raw SQL 은 ORM 을 거치지 않아
# datetime 을 그대로 바인딩하면 sqlite3 의 기본 어댑터(파이썬 3.12 에서 폐기)를 타므로 직접 맞춘다.
_STORED_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def _as_stored(moment: datetime) -> str:
    """저장된 것과 같은 문자열로. 고정 폭이라 사전순 비교가 곧 시간순 비교다."""
    return moment.strftime(_STORED_DATETIME_FORMAT)


def _rrf_merge(*ranked_lists: list[ChunkKey]) -> dict[ChunkKey, float]:
    """각 순위 목록에 대해 1/(RRF_K + rank)를 계산해 청크별로 합산한다."""
    scores: dict[ChunkKey, float] = {}
    for ranked_keys in ranked_lists:
        for rank, key in enumerate(ranked_keys, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def _documents_within(db: Session, document_ids: set[str], window: TimeWindow) -> set[str]:
    """주어진 문서 중 기간 안에 수집된 것들의 id.

    IN 목록이 검색이 뽑아 온 문서 수만큼으로 묶여 있어, 기간이 아무리 넓어도 조회가 커지지 않는다.
    반대로 기간 안의 문서를 통째로 불러와 거르는 방식은 '이번 달'만 해도 목록이 수천 건이 된다.
    """
    if not document_ids:
        return set()
    return set(
        db.scalars(
            select(Document.document_id).where(
                Document.document_id.in_(document_ids),
                Document.timestamp >= window.since,
                Document.timestamp < window.until,
            )
        )
    )


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


def _vector_search_if_usable(db: Session, query: str, limit: int) -> list[ChunkKey]:
    """색인이 지금 임베딩으로 만들어져 있을 때만 벡터 검색을 한다.

    임베딩 제공자나 모델을 바꾸고 재색인하지 않으면 색인에는 다른 공간의 좌표가 들어 있다. 차원이
    다르면 sqlite-vec가 오류를 내며 검색 전체가 실패하고, 차원이 같아도 값이 무의미해 엉뚱한 문서가
    올라온다. 어느 쪽이든 쓸 수 없으므로 전문 검색만으로 답한다 — 검색이 아예 안 되는 것보다는
    낫고, 재색인이 필요하다는 사실은 설정 화면이 알린다(reindex_required).
    """
    current = get_settings()
    if not current.vector_index_usable:
        logger.warning(
            "skipping vector search: index built with {!r} but settings say {!r} — reindex needed",
            current.indexed_signature,
            current.embedding_signature,
        )
        return []
    return _vector_search(db, embed_query(query), limit)


def _fts_search(db: Session, nouns: list[str], limit: int, window: TimeWindow | None = None) -> list[ChunkKey]:
    """명사를 OR로 묶어 매칭하고, 명사 중 실제 색인된 글에 등장한 개수가 required_matches(최소 매칭
    단어 수) 미만인 결과는 약한 매칭으로 보고 제외한다.

    등장 여부는 제목과 청크 본문을 합쳐서 센다. 색인이 둘을 함께 매칭하므로(chunk_fts 는 title 과
    body 를 모두 인덱스한다) 여기서 본문만 보면, 제목으로 걸린 결과가 매칭 0개로 세어져 전부
    걸러진다.

    window가 있으면 그 기간에 수집된 문서만 본다. 거르는 자리가 SQL 안인 것이 중요하다 — 뽑아 온
    뒤에 거르면 상위 limit건이 기간 밖 문서로 채워져, 정작 그 기간의 문서가 밀려난 채로 0건이 된다.
    """
    if not nouns:
        return []

    fts_query = " OR ".join(nouns)
    parameters = {"query": fts_query, "limit": limit}
    if window is None:
        fts_hits = db.execute(FTS_SEARCH_SQL, parameters).all()
    else:
        fts_hits = db.execute(
            FILTERED_FTS_SEARCH_SQL,
            {**parameters, "since": _as_stored(window.since), "until": _as_stored(window.until)},
        ).all()
    required_matches = min(settings.min_fts_matched_terms, len(nouns))

    fts_keys: list[ChunkKey] = []
    for vector_key, _rank, title, body in fts_hits:
        haystack = f"{title}\n{body}".lower()
        matched_terms = sum(1 for noun in nouns if noun.lower() in haystack)
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


def search_history(
    query: str,
    db: Session,
    limit: int = 50,
    count: int | None = None,
    window: TimeWindow | None = None,
) -> list[ChatResult]:
    """query와 가장 유사한 검색 기록(문서)을 벡터/FTS 검색 후 RRF로 병합해 상위 count개 문서를 반환한다.

    query는 전처리(services/preprocess.py)에서 지시 표현까지 풀어낸 검색어를 그대로 받는다.
    count도 같은 단계에서 넘어온 사용자가 요청한 결과 개수이며, 없거나 0 이하면 기본값을 쓴다.
    window가 있으면 그 기간에 수집된 문서만 대상으로 한다.

    기간이 걸린 검색이 0건이어도 기간을 풀어 다시 찾지는 않는다. 사용자는 "어제 본 것"을 물었고,
    그때 그저께 것을 내놓으면 어제 본 것이라고 오해한 채로 읽는다.
    """
    count = count if count and count > 0 else DEFAULT_RESULT_COUNT

    # 기간 밖 청크가 얼마나 섞여 있을지 모르므로, 걸러낼 것을 감안해 더 뽑는다.
    vector_limit = limit * FILTERED_VECTOR_LIMIT_FACTOR if window else limit
    vector_keys = _vector_search_if_usable(db, query, vector_limit)

    nouns = extract_nouns(query)
    fts_keys = _fts_search(db, nouns, limit, window)

    if window is not None:
        # 벡터 쪽은 여기서 거른다. 거르고 난 목록을 그대로 RRF에 넘기므로 순위는 남은 청크들로
        # 다시 매겨진다 — 빠진 청크의 원래 등수를 그대로 두면 1위가 없는 목록이 생겨 점수가
        # 한쪽으로 기운다.
        within = _documents_within(db, {document_id for document_id, _seq in vector_keys}, window)
        vector_keys = [key for key in vector_keys if key[0] in within][:limit]

    document_best = _merge_document_scores(vector_keys, fts_keys)
    if not document_best:
        logger.info(
            "search found no match: query={!r} period={} vector_hits={} fts_hits={}",
            query,
            window.label if window else None,
            len(vector_keys),
            len(fts_keys),
        )
        return []

    results = _fetch_top_results(db, document_best, count)
    logger.info(
        "search matched {} document(s): query={!r} period={} top_score={:.4f}",
        len(results),
        query,
        window.label if window else None,
        max(score for score, _seq in document_best.values()),
    )
    return results


def list_recent(window: TimeWindow, db: Session, count: int | None = None) -> list[ChatResult]:
    """기간만 말한 질의에 답한다 — 그 기간에 수집된 문서를 최근 순으로 늘어놓는다.

    "어제 본 거 다 보여줘"에는 찾을 낱말이 없다. 그대로 검색을 태우면 명사가 없어 전문 검색은 빈
    손이고 벡터 검색은 아무 문서나 끌어오므로, 검색을 건너뛰고 시간만으로 고른다.

    발췌는 질문과 맞물리는 구간을 고를 근거가 없어(질문에 낱말이 없다) 본문 앞부분을 쓴다. score는
    순위가 아니라 시간순이라 뜻이 없으므로 0.0으로 둔다 — 화면은 이 값을 쓰지 않는다.
    """
    count = count if count and count > 0 else LISTING_RESULT_COUNT
    documents = db.scalars(
        select(Document)
        .where(Document.timestamp >= window.since, Document.timestamp < window.until)
        .order_by(Document.timestamp.desc())
        .limit(count)
    ).all()

    logger.info("listing {} document(s) collected in {}", len(documents), window.label)
    return [
        ChatResult(
            document_id=document.document_id,
            url=document.url,
            title=document.title,
            score=0.0,
            snippet=document.full_text[:SNIPPET_CHARS],
        )
        for document in documents
    ]
