from collections.abc import Sequence

from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.models.conversation import (
    TITLE_MAX_CHARS,
    Conversation,
    Message,
    MessageRole,
)
from backend.schemas.conversation import (
    ConversationDetail,
    ConversationMessage,
    ConversationResult,
    ConversationSummary,
)
from backend.services.results import load_shown_documents


def ensure_conversation(conversation_id: str | None, db: Session) -> str:
    """이어갈 대화를 확정해 그 conversation_id를 반환한다.

    클라이언트가 보낸 id를 그대로 믿고 행을 만들지는 않는다. 모르는 id를 받으면 새 대화를 열고
    응답으로 새 id를 돌려주므로, 클라이언트는 받은 값으로 갱신하면 대화가 이어진다.
    """
    if conversation_id is not None:
        if load_conversation(conversation_id, db) is not None:
            return conversation_id
        logger.warning("unknown conversation_id={!r}, starting a new conversation instead", conversation_id)

    conversation = Conversation()
    db.add(conversation)
    db.flush()  # 파이썬 측 default(uuid4)를 확정시켜 commit 후 재조회 없이 id를 읽는다
    new_id = conversation.conversation_id
    db.commit()
    logger.info("conversation started: conversation_id={}", new_id)
    return new_id


def append_message(
    conversation_id: str,
    role: MessageRole,
    content: str,
    db: Session,
    result_document_ids: list[str] | None = None,
) -> None:
    """대화에 메시지 한 건을 덧붙인다.

    result_document_ids는 그 턴이 사용자에게 보여준 결과 목록이다. 빈 목록은 NULL로 눕혀 저장한다
    — 뒤에서 '결과가 있던 마지막 턴'을 고를 때 결과 없는 턴이 걸리지 않게 하려는 것이다.

    role이 user이면 title도 함께 확정을 시도한다. title이 이미 있으면 WHERE 조건에 걸려 UPDATE가
    아무 일도 하지 않으므로, 여러 번 불려도 대화의 첫 user 메시지로만 채워진다.
    """
    db.add(
        Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            result_document_ids=result_document_ids or None,
        )
    )
    if role == MessageRole.USER:
        title = _as_title(content)
        if title is not None:
            db.execute(
                update(Conversation)
                .where(Conversation.conversation_id == conversation_id, Conversation.title.is_(None))
                .values(title=title)
            )
    db.commit()
    logger.debug("message appended: conversation_id={} role={} chars={}", conversation_id, role, len(content))


def load_recent_messages(
    conversation_id: str,
    db: Session,
    limit: int | None = None,
    max_chars: int | None = None,
) -> list[Message]:
    """대화의 최근 메시지를 오래된 것부터 시간순으로 반환한다. 건수와 글자 수 두 상한을 함께 건다.

    limit·max_chars를 생략하면 settings.chat_history_messages·chat_history_max_chars를 쓴다. 최신
    limit건을 고른 뒤 되돌려야 하므로 id 내림차순으로 조회하고 순서를 뒤집는다.

    건수만으로는 프롬프트 크기가 정해지지 않아 글자 예산을 함께 둔다 — 긴 글을 붙여넣은 턴이
    몇 건 섞이면 같은 10건도 수만 자가 된다. 예산이 있으니 건수 쪽은 넉넉히 잡아도 안전하다.
    """
    limit = settings.chat_history_messages if limit is None else limit
    max_chars = settings.chat_history_max_chars if max_chars is None else max_chars
    if limit <= 0 or max_chars <= 0:
        return []

    recent = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()

    kept = _fit_char_budget(recent, max_chars)
    if len(kept) < len(recent):
        logger.debug(
            "history trimmed to fit {} chars: conversation_id={} {} -> {} message(s)",
            max_chars,
            conversation_id,
            len(recent),
            len(kept),
        )
    return list(reversed(kept))


def load_conversation(conversation_id: str, db: Session) -> Conversation | None:
    """대화 행 자체를 반환한다. 모르는 id면 None."""
    return db.scalar(select(Conversation).where(Conversation.conversation_id == conversation_id))


def load_all_messages(conversation_id: str, db: Session) -> list[Message]:
    """대화의 모든 메시지를 오래된 것부터 시간순으로 반환한다."""
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    ).all()
    return list(messages)


def rename_conversation(conversation_id: str, title: str, db: Session) -> bool:
    """대화 제목을 사용자가 지정한 값으로 바꾼다. 모르는 id면 아무것도 하지 않고 False.

    title은 이미 스키마(ConversationRenameRequest)에서 앞뒤 공백을 지우고 길이를 검증했으므로
    여기서는 그대로 쓴다.
    """
    conversation = load_conversation(conversation_id, db)
    if conversation is None:
        return False

    conversation.title = title
    db.commit()
    logger.info("conversation renamed: conversation_id={} title={!r}", conversation_id, title)
    return True


def delete_conversation(conversation_id: str, db: Session) -> bool:
    """대화와 그 메시지를 모두 지운다. 모르는 id면 아무것도 하지 않고 False.

    Message.conversation_id는 FK로 선언돼 있지만 SQLite는 PRAGMA foreign_keys=ON 없이는 이를
    강제하지 않고 session.py도 그 설정을 켜지 않는다. 그래서 messages를 여기서 먼저 명시적으로
    지운다 — 안 지우면 고아 행으로 남아 조회는 안 돼도 자리만 차지한다.
    """
    conversation = load_conversation(conversation_id, db)
    if conversation is None:
        return False

    db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    db.delete(conversation)
    db.commit()
    logger.info("conversation deleted: conversation_id={}", conversation_id)
    return True


def load_conversation_detail(conversation_id: str, db: Session) -> ConversationDetail | None:
    """대화 한 건의 전문을 반환한다. 모르는 id면 None.

    load_recent_messages와 달리 잘라내지 않는다. 대화를 화면에 되살리는 용도라 전부 필요하다.

    content에는 답변 문장만 남아 그것만으로는 결과 카드를 다시 그릴 수 없다. 그 턴이 보여준
    document_id는 남아 있으므로 문서를 조인해 제목과 URL을 되살린다(services/results.py).
    """
    conversation = load_conversation(conversation_id, db)
    if conversation is None:
        return None

    messages = load_all_messages(conversation_id, db)
    shown = load_shown_documents(messages, db)

    return ConversationDetail(
        conversation_id=conversation.conversation_id,
        created_at=conversation.created_at,
        messages=[
            ConversationMessage(
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                results=[
                    ConversationResult(
                        document_id=document.document_id,
                        title=document.title,
                        url=document.url,
                        visited_at=document.timestamp,
                    )
                    for document in shown.get(message.id, ())
                ],
            )
            for message in messages
        ],
    )


def list_conversations(db: Session, limit: int) -> list[ConversationSummary]:
    """대화 목록을 최근 활동 순으로 최대 limit건 반환한다.

    title은 append_message가 채워둔 값을 그대로 읽는다. message_count·last_message_at은 컬럼으로
    두지 않았으므로 여전히 messages를 집계해 구한다.
    """
    activity = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count().label("message_count"),
            func.max(Message.created_at).label("last_message_at"),
            func.max(Message.id).label("last_message_id"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    rows = db.execute(
        select(
            Conversation.conversation_id,
            Conversation.title,
            Conversation.created_at,
            func.coalesce(activity.c.message_count, 0).label("message_count"),
            activity.c.last_message_at,
        )
        .outerjoin(activity, activity.c.conversation_id == Conversation.conversation_id)
        # 메시지가 없는 대화는 정렬할 활동 시각이 없어 생성 시각으로 대신한다. 두 시각 모두 초
        # 단위라 같은 초에 몰린 대화끼리는 갈리지 않으므로, 단조 증가하는 id를 뒤 기준으로 둔다.
        .order_by(
            func.coalesce(activity.c.last_message_at, Conversation.created_at).desc(),
            func.coalesce(activity.c.last_message_id, 0).desc(),
            Conversation.id.desc(),
        )
        .limit(limit)
    ).all()

    return [
        ConversationSummary(
            conversation_id=row.conversation_id,
            title=row.title,
            message_count=row.message_count,
            created_at=row.created_at,
            last_message_at=row.last_message_at,
        )
        for row in rows
    ]


def _fit_char_budget(recent: Sequence[Message], max_chars: int) -> list[Message]:
    """최신 메시지부터 훑어 글자 예산에 들어가는 만큼만 남긴다. 입력도 반환도 최신순이다.

    예산을 넘기는 메시지를 만나면 거기서 멈춘다. 그 한 건만 건너뛰고 더 오래된 메시지를 채우면
    대화 중간이 빈 채로 이어져, 맥락을 주기는커녕 없던 흐름을 지어내게 된다.

    최신 한 건이 혼자 예산을 넘으면 빈 목록이 된다. 이때는 맥락 없이 이번 입력만으로 답하게
    되는데, 그 한 건이 프롬프트를 통째로 밀어내는 것보다 낫다고 보고 그대로 둔다.
    """
    kept: list[Message] = []
    used = 0
    for message in recent:
        used += len(message.content)
        if used > max_chars:
            break
        kept.append(message)
    return kept


def _as_title(first_question: str) -> str | None:
    """첫 질문을 title 컬럼에 넣을 한 줄로 줄인다.

    본문 전체를 저장하지 않기 위해 여기서 자른다(컬럼 길이도 이에 맞춰져 있다). 개행은 한 줄로
    접는다. 접은 결과가 빈 문자열이면(공백뿐인 메시지) None을 돌려줘 title을 채우지 않는다.
    """
    title = " ".join(first_question.split())
    if not title:
        return None
    if len(title) <= TITLE_MAX_CHARS:
        return title
    return title[:TITLE_MAX_CHARS].rstrip() + "…"
