from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.collect import CollectRequest, CollectResponse
from backend.services.document import save_collected_document

router = APIRouter(tags=["collect"])


@router.post("/collect")
def collect(request: CollectRequest, db: Session = Depends(get_db)) -> CollectResponse:
    save_collected_document(request, db)
    return CollectResponse(status="ok")
