from datetime import datetime

from pydantic import BaseModel, field_validator

from backend.models.conversation import TITLE_MAX_CHARS


class ConversationSummary(BaseModel):
    """목록 한 줄.

    title은 Conversation.title을 그대로 읽은 값이고, last_message_at과 message_count는 매번
    messages를 집계해서 구한다. 메시지가 없는 대화(생성만 하고 쓰지 않은 경우)에서는 title과
    last_message_at 모두 None이고 message_count는 0이다.
    """

    conversation_id: str
    title: str | None = None
    message_count: int
    created_at: datetime
    last_message_at: datetime | None = None


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]


class ConversationMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class ConversationDetail(BaseModel):
    """대화 한 건의 전문. messages는 오래된 것부터 시간순이다."""

    conversation_id: str
    created_at: datetime
    messages: list[ConversationMessage]


class ConversationRenameRequest(BaseModel):
    """PATCH /conversations/{id} 요청 본문.

    append_message가 채우는 title(첫 질문에서 자동으로 뽑아냄)과 달리 사용자가 직접 입력한
    값을 그대로 쓴다. 앞뒤 공백만 지우고, 그 결과가 빈 문자열이거나 너무 길면 거부한다.
    """

    title: str

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        if len(stripped) > TITLE_MAX_CHARS:
            raise ValueError(f"title must be at most {TITLE_MAX_CHARS} characters")
        return stripped
