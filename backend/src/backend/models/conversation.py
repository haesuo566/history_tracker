from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class MessageRole(StrEnum):
    """대화에 저장되는 메시지의 화자."""

    USER = "user"
    ASSISTANT = "assistant"


class Conversation(Base):
    """이어지는 대화 한 세션. 실제 내용은 Message에 있고 여기엔 세션 식별자만 둔다."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(unique=True, index=True, default=lambda: str(uuid4()))
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
