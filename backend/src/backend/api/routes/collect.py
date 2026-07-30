import hashlib

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.models.document import Document
from backend.schemas.collect import CollectRequest, CollectResponse

router = APIRouter(tags=["collect"])


@router.post("/collect")
def collect(request: CollectRequest, db: Session = Depends(get_db)):
    content_hash = hashlib.sha256(request.content.encode()).hexdigest()
    stmt = (
        insert(Document)
        .values(
            url=request.url,
            title=request.title,
            full_text=request.content,
            hash=content_hash,
            timestamp=request.startTime,
        )
        .on_conflict_do_nothing(index_elements=[Document.hash])
    )
    db.execute(stmt)
    db.commit()
    return CollectResponse(status="ok")
