from dataclasses import dataclass

from loguru import logger
from sqlalchemy.orm import Session

from backend.models.conversation import MessageRole
from backend.models.document import Document
from backend.services.conversation import (
    append_message,
    ensure_conversation,
    load_recent_messages,
)
from backend.services.detail import load_candidates, resolve_target
from backend.services.intent import Intent, classify_by_regex
from backend.services.query_parser import rewrite_query


@dataclass(frozen=True)
class PreprocessedMessage:
    """전처리를 마친 한 턴의 입력. 이후 단계는 원문 대신 이 값을 보고 움직인다.

    intent가 ETC면 query는 쓰이지 않는다(원문이 그대로 들어 있다). DETAIL이면 target_document가
    반드시 채워져 있다 — 지목한 문서를 특정하지 못한 턴은 RECALL로 내려보내므로, 이후 단계는
    'DETAIL인데 대상이 없는' 경우를 다룰 필요가 없다.
    """

    conversation_id: str
    intent: Intent
    query: str
    desired_count: int | None = None
    target_document: Document | None = None


def _settle_intent(by_regex: Intent | None, by_rewrite: Intent, has_candidates: bool) -> Intent:
    """정규식 판정과 재작성 판정을 합쳐 이 턴의 의도를 확정한다."""
    if by_rewrite is Intent.DETAIL and not has_candidates:
        # 지목할 결과가 아직 없는 턴은 상세 요청이 될 수 없다. 기록을 새로 뒤지는 쪽으로 내린다.
        logger.debug("detail needs a previous result list to point at, downgrading to recall")
        return Intent.RECALL
    if by_regex is Intent.RECALL:
        # 정규식이 확신한 '기록 관련'은 잡담으로 뒤집지 않는다. 다만 recall/detail의 구분은 앞선
        # 대화를 봐야 갈리고 정규식은 애초에 그 둘을 가리지 못하므로, detail이라는 판정만은 받는다.
        return Intent.DETAIL if by_rewrite is Intent.DETAIL else Intent.RECALL
    return by_rewrite


def preprocess_message(message: str, conversation_id: str | None, db: Session) -> PreprocessedMessage:
    """검색·응답 단계로 넘기기 전에 대화 처리와 의도 판단, 질의 재작성을 한 번에 끝낸다.

    대화 처리는 이어갈 대화를 확정하고 이번 입력을 저장하는 것까지다. 그다음 이 턴이 무엇인지와
    무엇을 검색할지를 정하는데, 둘은 한 번의 Gemini 호출로 함께 받는다. '그거 뭐였지'가 무엇을
    가리키는지 찾는 일과 이 턴이 recall인지 판단하는 일이 같은 추론이라서다. 그래서 의도 분류에도
    대화 맥락이 필요하며, 그 맥락을 들고 있는 곳이 바로 이 재작성 호출이다. detail 턴이 지목한
    문서를 고르는 것도 같은 이유로 같은 호출에 얹는다(services/detail.py).

    두 판정을 합치는 규칙은 _settle_intent에 있다.
    """
    conversation_id = ensure_conversation(conversation_id, db)
    # 이번 입력을 저장하기 전에 읽어야 history가 "직전까지의 대화"가 된다.
    history = load_recent_messages(conversation_id, db)
    append_message(conversation_id, MessageRole.USER, message, db)

    by_regex = classify_by_regex(message)
    if by_regex is Intent.ETC:
        # 잡담은 검색을 타지 않으니 재작성할 것이 없다. 여기서 끊어 Gemini 호출을 아낀다.
        logger.debug("intent classified by regex: {!r} -> {} (skipping query rewrite)", message, by_regex)
        return PreprocessedMessage(conversation_id=conversation_id, intent=by_regex, query=message)

    candidates = load_candidates(history, db)
    parsed = rewrite_query(message, history, candidates)
    intent = _settle_intent(by_regex, parsed.intent, bool(candidates))

    target_document = None
    if intent is Intent.DETAIL:
        target_document = resolve_target(parsed.query, parsed.target_index, candidates)
        if target_document is None:
            # 어느 것을 말하는지 못 고른 채로 상세 답변을 하면 엉뚱한 문서를 근거로 삼게 된다.
            # 기록을 새로 뒤지는 쪽이 낫다.
            logger.info("detail target unresolved, downgrading to recall: query={!r}", parsed.query)
            intent = Intent.RECALL

    logger.debug(
        "message preprocessed: {!r} -> intent={} query={!r} (regex={} rewrite={} target={!r})",
        message,
        intent,
        parsed.query,
        by_regex,
        parsed.intent,
        target_document.title if target_document else None,
    )
    return PreprocessedMessage(
        conversation_id=conversation_id,
        intent=intent,
        query=parsed.query,
        desired_count=parsed.desired_count,
        target_document=target_document,
    )
