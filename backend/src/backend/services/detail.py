"""이미 찾아준 결과 중 사용자가 지목한 문서 한 건을 특정한다.

특정은 두 단계다. 1차는 질의 재작성 호출이 후보 목록을 보고 고른 번호(target_index)다 —
'두 번째 것'(순서), '쿠버네티스 그거'(제목), 'velog에서 본 거'(URL)가 전부 한 번의 추론으로
풀리고, detail 판정을 위해 어차피 부르는 호출이라 비용도 늘지 않는다. 2차는 그 번호가 없거나
범위를 벗어났을 때의 문자열 매칭이다(재작성 응답 파싱 실패 경로도 여기로 온다).

둘 다 실패하면 아무거나 고르지 않고 None을 돌려준다. 엉뚱한 문서를 근거로 그럴듯하게 답하는
것이 가장 나쁜 실패라, 그럴 바엔 기록을 새로 뒤지는 쪽(recall)으로 내려보낸다.
"""

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from loguru import logger

from backend.models.document import Document
from backend.schemas.chat import ChatResult
from backend.services.tokenizer import extract_nouns

# 1위 점수가 이 값에 못 미치면 후보 중 아무것도 지목되지 않은 것으로 본다.
MIN_MATCH_SCORE = 0.4
# 1위와 2위가 이만큼도 안 벌어지면 찍는 것과 같다.
MIN_MATCH_MARGIN = 0.05
SNIPPET_CHARS = 300

_NON_WORD = re.compile(r"[^0-9a-z가-힣]+")
_ASCII_WORD = re.compile(r"[a-z0-9]+")


def resolve_target(query: str, target_index: int | None, candidates: Sequence[Document]) -> Document | None:
    """지목된 문서를 특정한다. 확신할 수 없으면 None."""
    if not candidates:
        return None

    if target_index is not None:
        if 1 <= target_index <= len(candidates):
            return candidates[target_index - 1]
        logger.warning("target_index={} is out of range (candidates={})", target_index, len(candidates))

    return _best_match(query, candidates)


def as_chat_result(document: Document) -> ChatResult:
    """지목된 문서를 검색 결과와 같은 모양으로 감싼다.

    검색을 거치지 않았으므로 score는 순위가 아니라 '직접 지목됨'을 뜻하는 1.0이다. snippet은 질문과
    맞물리는 구간을 고를 방법이 아직 없어 본문 앞부분을 쓴다.
    """
    return ChatResult(
        document_id=document.document_id,
        url=document.url,
        title=document.title,
        score=1.0,
        snippet=document.full_text[:SNIPPET_CHARS],
    )


def _best_match(query: str, candidates: Sequence[Document]) -> Document | None:
    ranked = sorted(
        ((_score(query, candidate), candidate) for candidate in candidates),
        key=lambda scored: scored[0],
        reverse=True,
    )
    (best_score, best), *rest = ranked

    if best_score < MIN_MATCH_SCORE:
        logger.debug("no candidate matches {!r} (best={:.2f})", query, best_score)
        return None
    if rest and best_score - rest[0][0] < MIN_MATCH_MARGIN:
        logger.debug("candidates tie for {!r} ({:.2f} vs {:.2f})", query, best_score, rest[0][0])
        return None

    logger.debug("candidate matched by text: {!r} -> {!r} ({:.2f})", query, best.title, best_score)
    return best


def _score(query: str, document: Document) -> float:
    """질의가 이 문서를 가리키는 정도를 0~1로 매긴다.

    제목을 거의 그대로 말한 경우를 1.0으로 두고, 나머지는 두 관점의 최대값이다. 하나는 사용자가 말한
    낱말 중 몇 개가 이 문서에 있는지(조사·어미가 붙는 한국어에서 문자열 유사도보다 잘 맞는다),
    다른 하나는 문자열 유사도(부분 표현·표기 흔들림 보정)다. 후자는 제목이 길수록 값이 낮게 나오니
    낱말 쪽과 나란히 두기 위해 깎아서 쓴다.
    """
    normalized_query = _normalize(query)
    target = _normalize(f"{document.title} {document.url}")
    if normalized_query and normalized_query in target:
        return 1.0

    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0

    document_tokens = _tokens(document.title) | _tokens(document.url)
    coverage = len(query_tokens & document_tokens) / len(query_tokens)
    similarity = SequenceMatcher(None, normalized_query, target).ratio()
    return max(coverage, similarity * 0.8)


def _tokens(text: str) -> set[str]:
    """매칭 단위. 한국어는 명사만 남기고, kiwi가 명사로 잡지 않는 영문·숫자는 낱말 단위로 더한다."""
    lowered = text.lower()
    return {noun.lower() for noun in extract_nouns(text)} | set(_ASCII_WORD.findall(lowered))


def _normalize(text: str) -> str:
    return _NON_WORD.sub("", text.lower())
