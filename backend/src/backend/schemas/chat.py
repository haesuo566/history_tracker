from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """conversation_id를 넘기면 그 대화를 이어간다. 없으면 새 대화가 시작된다.

    client_now는 클라이언트의 현재 시각으로, 오프셋이 붙은 ISO 문자열을 기대한다("어제"의 경계는
    브라우저 앞에 앉은 사람의 자정이라 서버 시각으로는 알 수 없다). 없으면 UTC로 간주하고 경고를
    남긴다 — 옛 클라이언트도 기간 없는 질의는 그대로 동작해야 한다.
    """

    message: str
    conversation_id: str | None = None
    client_now: datetime | None = None


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
