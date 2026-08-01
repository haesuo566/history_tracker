from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class ChatResult(BaseModel):
    document_id: str
    url: str
    title: str
    score: float


class ChatResponse(BaseModel):
    result: ChatResult | None = None
    answer: str | None = None
