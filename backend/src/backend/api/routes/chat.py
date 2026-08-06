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
    elif prepared.intent == Intent.DETAIL:
        # TODO: 상세 검색 — 지목된 결과 하나를 골라 그 문서를 근거로 답한다.
        #   1) 직전 턴이 보여준 결과 목록에서 대상을 특정한다. prepared.query에 제목·키워드가
        #      들어오지만, '두 번째 것'처럼 순서로 지목하는 경우는 그 목록 자체가 있어야 풀린다
        #      (messages에는 답변 텍스트만 남고 ChatResult는 저장되지 않는다 — 보관 위치가 먼저).
        #   2) 대상 문서의 full_text를 청크 단위가 아니라 통째로 읽어 답변 근거로 넘긴다.
        #      desired_count는 이 경로에서 의미가 없다.
        # 그때까지는 RECALL과 같은 경로로 흘려 동작을 유지한다.
        results = search_history(prepared.query, db, count=prepared.desired_count)
        answer = generate_recall_answer(request.message, results)
    else:
        results = []
        answer = generate_answer(request.message)

    append_message(prepared.conversation_id, MessageRole.ASSISTANT, answer, db)
    return ChatResponse(conversation_id=prepared.conversation_id, results=results, answer=answer)
