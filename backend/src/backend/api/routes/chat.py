from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.models.conversation import MessageRole
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.answer import generate_answer, generate_recall_answer
from backend.services.conversation import (
    append_message,
    ensure_conversation,
    load_recent_messages,
)
from backend.services.intent import Intent, classify_intent
from backend.services.search import search_history

router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    conversation_id = ensure_conversation(request.conversation_id, db)
    # 이번 입력을 저장하기 전에 읽어야 history가 "직전까지의 대화"가 된다.
    history = load_recent_messages(conversation_id, db)
    append_message(conversation_id, MessageRole.USER, request.message, db)

    intent = classify_intent(request.message)
    if intent == Intent.RECALL:
        results = search_history(request.message, db, history=history)
        answer = generate_recall_answer(request.message, results)
    else:
        results = []
        answer = generate_answer(request.message)

    append_message(conversation_id, MessageRole.ASSISTANT, answer, db)
    return ChatResponse(conversation_id=conversation_id, results=results, answer=answer)
