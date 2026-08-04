from pydantic import BaseModel


class ChatRequest(BaseModel):
    """conversation_id를 넘기면 그 대화를 이어간다. 없으면 새 대화가 시작된다."""

    message: str
    conversation_id: str | None = None


class ChatResult(BaseModel):
    document_id: str
    url: str
    title: str
    score: float
    snippet: str


class ChatResponse(BaseModel):
    """conversation_id는 항상 이번 요청이 실제로 사용한 대화의 id다.

    요청이 모르는 id를 보냈으면 새로 시작된 대화의 id가 들어오므로, 클라이언트는 매 응답의
    이 값으로 저장해 둔 id를 갱신하면 된다.
    """

    conversation_id: str
    results: list[ChatResult] = []
    answer: str | None = None
