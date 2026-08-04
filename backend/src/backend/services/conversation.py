from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.conversation import Conversation, Message, MessageRole


def ensure_conversation(conversation_id: str | None, db: Session) -> str:
    """이어갈 대화를 확정해 그 conversation_id를 반환한다.

    클라이언트가 보낸 id를 그대로 믿고 행을 만들지는 않는다. 모르는 id를 받으면 새 대화를 열고
    응답으로 새 id를 돌려주므로, 클라이언트는 받은 값으로 갱신하면 대화가 이어진다.
    """
    if conversation_id is not None:
        existing = db.scalar(select(Conversation).where(Conversation.conversation_id == conversation_id))
        if existing is not None:
            return conversation_id
        logger.warning("unknown conversation_id={!r}, starting a new conversation instead", conversation_id)

    conversation = Conversation()
    db.add(conversation)
    db.flush()  # 파이썬 측 default(uuid4)를 확정시켜 commit 후 재조회 없이 id를 읽는다
    new_id = conversation.conversation_id
    db.commit()
    logger.info("conversation started: conversation_id={}", new_id)
    return new_id


def append_message(conversation_id: str, role: MessageRole, content: str, db: Session) -> None:
    """대화에 메시지 한 건을 덧붙인다."""
    db.add(Message(conversation_id=conversation_id, role=role, content=content))
    db.commit()
    logger.debug("message appended: conversation_id={} role={} chars={}", conversation_id, role, len(content))


def load_recent_messages(conversation_id: str, db: Session, limit: int | None = None) -> list[Message]:
    """대화의 최근 메시지를 오래된 것부터 시간순으로 최대 limit건 반환한다.

    limit을 생략하면 settings.chat_history_messages를 쓴다. 최신 limit건을 고른 뒤 되돌려야 하므로
    id 내림차순으로 조회하고 순서를 뒤집는다.
    """
    limit = settings.chat_history_messages if limit is None else limit
    if limit <= 0:
        return []

    recent = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(recent))
