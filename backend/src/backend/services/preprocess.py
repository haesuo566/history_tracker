from dataclasses import dataclass

from loguru import logger
from sqlalchemy.orm import Session

from backend.models.conversation import MessageRole
from backend.services.conversation import (
    append_message,
    ensure_conversation,
    load_recent_messages,
)
from backend.services.intent import Intent, classify_by_regex
from backend.services.query_parser import rewrite_query


@dataclass(frozen=True)
class PreprocessedMessage:
    """전처리를 마친 한 턴의 입력. 이후 단계는 원문 대신 이 값을 보고 움직인다.

    intent가 ETC면 query는 쓰이지 않는다(원문이 그대로 들어 있다).
    """

    conversation_id: str
    intent: Intent
    query: str
    desired_count: int | None = None


def preprocess_message(message: str, conversation_id: str | None, db: Session) -> PreprocessedMessage:
    """검색·응답 단계로 넘기기 전에 대화 처리와 의도 판단, 질의 재작성을 한 번에 끝낸다.

    대화 처리는 이어갈 대화를 확정하고 이번 입력을 저장하는 것까지다. 그다음 이 턴이 무엇인지와
    무엇을 검색할지를 정하는데, 둘은 한 번의 Gemini 호출로 함께 받는다. '그거 뭐였지'가 무엇을
    가리키는지 찾는 일과 이 턴이 recall인지 판단하는 일이 같은 추론이라서다. 그래서 의도 분류에도
    대화 맥락이 필요하며, 그 맥락을 들고 있는 곳이 바로 이 재작성 호출이다.

    정규식이 확신하면 그 판정을 재작성 결과보다 우선한다. '찾아줘' 같은 키워드는 규칙만으로
    충분히 갈리고, 규칙 쪽이 결정적이라 테스트로 고정할 수 있다.
    """
    conversation_id = ensure_conversation(conversation_id, db)
    # 이번 입력을 저장하기 전에 읽어야 history가 "직전까지의 대화"가 된다.
    history = load_recent_messages(conversation_id, db)
    append_message(conversation_id, MessageRole.USER, message, db)

    intent = classify_by_regex(message)
    if intent is Intent.ETC:
        # 잡담은 검색을 타지 않으니 재작성할 것이 없다. 여기서 끊어 Gemini 호출을 아낀다.
        logger.debug("intent classified by regex: {!r} -> {} (skipping query rewrite)", message, intent)
        return PreprocessedMessage(conversation_id=conversation_id, intent=intent, query=message)

    parsed = rewrite_query(message, history)
    logger.debug(
        "message preprocessed: {!r} -> intent={} query={!r} (regex={})",
        message,
        intent or parsed.intent,
        parsed.query,
        intent,
    )
    return PreprocessedMessage(
        conversation_id=conversation_id,
        intent=intent or parsed.intent,
        query=parsed.query,
        desired_count=parsed.desired_count,
    )
