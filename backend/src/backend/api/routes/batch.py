from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.batch import BatchResponse
from backend.services.indexing import run_indexing_batch

router = APIRouter(tags=["batch"])


@router.post("/batch")
def batch(db: Session = Depends(get_db)) -> BatchResponse:
    return run_indexing_batch(db)
