from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class ChatResult(BaseModel):
    document_id: str
    url: str
    title: str
    score: float
    snippet: str


class ChatResponse(BaseModel):
    results: list[ChatResult] = []
    answer: str | None = None
