from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.models.conversation import MessageRole
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.answer import generate_answer, generate_detail_answer, generate_recall_answer
from backend.services.conversation import append_message
from backend.services.detail import as_chat_result
from backend.services.intent import Intent
from backend.services.preprocess import preprocess_message
from backend.services.search import search_history

router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    prepared = preprocess_message(request.message, request.conversation_id, db, request.client_now)

    # 답변은 재작성된 검색어가 아니라 원문을 근거로 만든다. 사용자가 실제로 물은 문장이다. 대신
    # 앞선 대화와 그 턴들이 보여준 목록을 함께 넘겨, '아까 그거'가 무엇인지 답변 단계도 알게 한다.
    context = (prepared.history, prepared.shown)
    if prepared.intent == Intent.RECALL:
        results = search_history(prepared.query, db, count=prepared.desired_count)
        answer = generate_recall_answer(request.message, results, *context)
    elif prepared.intent == Intent.DETAIL:
        # 지목된 문서 한 건만 근거로 삼는다. 검색을 다시 태우면 특정해 둔 그 문서가 아닌 것이 위로
        # 올라올 수 있어 지목이 무의미해진다. desired_count도 이 경로에선 뜻이 없다.
        results = [as_chat_result(prepared.target_document)]
        answer = generate_detail_answer(request.message, prepared.target_document, *context)
    else:
        results = []
        answer = generate_answer(request.message, *context)

    # detail 턴은 새 목록을 보여준 것이 아니라 이미 보여준 목록에서 하나를 설명한 턴이다. 그 한 건으로
    # 후보 목록을 갈아치우면 '아니 세 번째 것' 같은 연속 지목이 막히므로, 목록을 갱신하지 않는다.
    shown_document_ids = (
        [] if prepared.intent == Intent.DETAIL else [result.document_id for result in results]
    )
    append_message(
        prepared.conversation_id,
        MessageRole.ASSISTANT,
        answer,
        db,
        result_document_ids=shown_document_ids,
    )
    return ChatResponse(conversation_id=prepared.conversation_id, results=results, answer=answer)
