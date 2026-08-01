from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.answer import generate_answer
from backend.services.intent import Intent, classify_intent
from backend.services.search import search_history

router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    intent = classify_intent(request.message)

    if intent == Intent.RECALL:
        results = search_history(request.message, db)
        return ChatResponse(result=results[0] if results else None)

    return ChatResponse(answer=generate_answer(request.message))
