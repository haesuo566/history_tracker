from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.models.conversation import MessageRole
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.answer import generate_answer, generate_recall_answer
from backend.services.conversation import append_message
from backend.services.intent import Intent
from backend.services.preprocess import preprocess_message
from backend.services.search import search_history

router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    prepared = preprocess_message(request.message, request.conversation_id, db)

    # 답변은 재작성된 검색어가 아니라 원문을 근거로 만든다. 사용자가 실제로 물은 문장이다.
    if prepared.intent == Intent.RECALL:
        results = search_history(prepared.query, db, count=prepared.desired_count)
        answer = generate_recall_answer(request.message, results)
    else:
        results = []
        answer = generate_answer(request.message)

    append_message(prepared.conversation_id, MessageRole.ASSISTANT, answer, db)
    return ChatResponse(conversation_id=prepared.conversation_id, results=results, answer=answer)
