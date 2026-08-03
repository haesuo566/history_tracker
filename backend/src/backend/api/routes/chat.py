from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.answer import generate_answer, generate_recall_answer
from backend.services.intent import Intent, classify_intent
from backend.services.search import search_history

router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    intent = classify_intent(request.message)

    if intent == Intent.RECALL:
        results = search_history(request.message, db)
        answer = generate_recall_answer(request.message, results)
        return ChatResponse(results=results, answer=answer)

    return ChatResponse(answer=generate_answer(request.message))
