from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.models.conversation import MessageRole
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.chat.answer import generate_answer, generate_detail_answer, generate_recall_answer
from backend.services.chat.detail import as_chat_result
from backend.services.chat.intent import Intent
from backend.services.chat.preprocess import preprocess_message
from backend.services.conversation.store import append_message
from backend.services.dashboard.builder import build_dashboard
from backend.services.search.hybrid import list_recent, search_history

router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    prepared = preprocess_message(request.message, request.conversation_id, db, request.client_now)

    # 답변은 재작성된 검색어가 아니라 원문을 근거로 만든다. 사용자가 실제로 물은 문장이다. 대신
    # 앞선 대화와 그 턴들이 보여준 목록을 함께 넘겨, '아까 그거'가 무엇인지 답변 단계도 알게 한다.
    context = (prepared.history, prepared.shown)
    dashboard = None
    if prepared.intent == Intent.DASHBOARD:
        # 기록을 찾지 않고 센다. 결과 카드가 없으니 다음 턴의 지목 후보 목록도 바뀌지 않는다.
        results = []
        outcome = build_dashboard(
            request.message, db, *context, window=prepared.window, client_now=request.client_now
        )
        answer, dashboard = outcome.answer, outcome.dashboard
    elif prepared.intent == Intent.RECALL:
        # "어제 본 거 다 보여줘"에는 찾을 낱말이 없다. 그대로 검색을 태우면 명사가 없어 전문
        # 검색은 빈손이고 벡터 검색은 아무 문서나 끌어오므로, 기간만으로 늘어놓는다.
        if prepared.window is not None and not prepared.query.strip():
            results = list_recent(prepared.window, db, count=prepared.desired_count)
        else:
            results = search_history(
                prepared.query, db, count=prepared.desired_count, window=prepared.window
            )
        answer = generate_recall_answer(
            request.message, results, *context, window=prepared.window, client_now=request.client_now
        )
    elif prepared.intent == Intent.DETAIL:
        # 지목된 문서 한 건만 근거로 삼는다. 검색을 다시 태우면 특정해 둔 그 문서가 아닌 것이 위로
        # 올라올 수 있어 지목이 무의미해진다. desired_count도 이 경로에선 뜻이 없다.
        results = [as_chat_result(prepared.target_document)]
        answer = generate_detail_answer(
            request.message, prepared.target_document, *context, client_now=request.client_now
        )
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
        dashboard=dashboard,
    )
    return ChatResponse(
        conversation_id=prepared.conversation_id, results=results, answer=answer, dashboard=dashboard
    )
