from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

TITLE_MAX_CHARS = 60


class MessageRole(StrEnum):
    """대화에 저장되는 메시지의 화자."""

    USER = "user"
    ASSISTANT = "assistant"


class Conversation(Base):
    """이어지는 대화 한 세션. 실제 내용은 Message에 있고 여기엔 세션 식별자만 둔다.

    title은 첫 user 메시지가 저장되는 시점에 한 번 채워지고(services.conversation.append_message),
    이후 사용자가 PATCH /conversations/{id}(services.conversation.rename_conversation)로 직접
    바꿀 수도 있다. TITLE_MAX_CHARS자로 자르고 말줄임표(1자)를 붙이므로 컬럼 길이는 +1.
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(unique=True, index=True, default=lambda: str(uuid4()))
    title: Mapped[str | None] = mapped_column(String(TITLE_MAX_CHARS + 1))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    """대화에 오간 메시지 한 건. 순서는 created_at이 아니라 id로 판단한다.

    created_at은 초 단위라 같은 요청에서 저장한 user/assistant 메시지가 동일한 값을 갖는다.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.conversation_id"), index=True)
    role: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    # 그 턴이 사용자에게 보여준 결과의 document_id를 보여준 순서대로 남긴다. '두 번째 것'처럼
    # 지목하는 detail 턴은 목록 자체가 있어야 풀리는데, content에는 답변 문장만 남아 제목이 실리지
    # 않은 턴은 되짚을 수 없다. 결과가 없던 턴은 NULL이라 '결과가 있던 마지막 턴'을 그대로 고른다.
    result_document_ids: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
