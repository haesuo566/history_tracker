from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.search import search_history

router = APIRouter(tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    result = search_history(request.message, db)
    return ChatResponse(result=result)
