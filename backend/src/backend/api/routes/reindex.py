from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.reindex import ReindexResponse
from backend.services.reindex import reset_index
from backend.services.tei import TeiError

router = APIRouter(tags=["reindex"])


@router.post("/reindex")
def reindex(db: Session = Depends(get_db)) -> ReindexResponse:
    """색인을 비우고 모든 문서를 색인 대기로 되돌린다. 다시 쌓는 것은 POST /batch 다."""
    try:
        return reset_index(db)
    except (TeiError, RuntimeError) as error:
        # 임베딩 제공자에 붙지 못해 차원을 못 알아낸 경우다. 색인은 아직 그대로다.
        raise HTTPException(status_code=502, detail=str(error)) from error
