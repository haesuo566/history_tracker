from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.conversation import (
    ConversationDetail,
    ConversationListResponse,
)
from backend.services.conversation import (
    delete_conversation,
    list_conversations,
    load_conversation_detail,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_all(
    limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)
) -> ConversationListResponse:
    return ConversationListResponse(conversations=list_conversations(db, limit))


@router.get("/{conversation_id}")
def detail(conversation_id: str, db: Session = Depends(get_db)) -> ConversationDetail:
    conversation = load_conversation_detail(conversation_id, db)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conversation


@router.delete("/{conversation_id}", status_code=204)
def delete(conversation_id: str, db: Session = Depends(get_db)) -> None:
    if not delete_conversation(conversation_id, db):
        raise HTTPException(status_code=404, detail="conversation not found")
