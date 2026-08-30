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


class ConversationResult(BaseModel):
    """되살린 결과 카드 한 줄.

    ChatResult를 재사용하지 않는 것은 score와 snippet 때문이다. 둘은 그때의 검색이 만든 값이라
    저장되지 않았고 재현할 수도 없다. 없는 값을 0.0이나 빈 문자열로 채워 내보내면 받는 쪽이 그것을
    실제 점수로 읽는다.
    """

    document_id: str
    title: str
    url: str


class ConversationMessage(BaseModel):
    """대화에 남은 메시지 한 건.

    results는 그 턴이 사용자에게 보여준 결과 목록을 보여준 순서대로 되살린 것이다(services/results.py).
    결과가 없던 턴, 결과 목록을 남기지 않는 detail 턴, 그리고 result_document_ids 컬럼이 생기기 전에
    쌓인 메시지는 빈 목록이다.
    """

    role: str
    content: str
    created_at: datetime
    results: list[ConversationResult] = []


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
