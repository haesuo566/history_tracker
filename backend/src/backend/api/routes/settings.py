from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.settings import SettingsResponse, SettingsUpdateRequest
from backend.services.runtime_settings import describe_settings, save_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def read(db: Session = Depends(get_db)) -> SettingsResponse:
    return describe_settings(db)


@router.patch("")
def update(request: SettingsUpdateRequest, db: Session = Depends(get_db)) -> SettingsResponse:
    """넘어온 항목만 저장하고 갱신된 설정 전체를 돌려준다.

    갱신 결과를 돌려주는 것은 화면이 저장 직후 다시 GET 하지 않아도 되게 하려는 것이다. 값 하나만
    바꿔도 마스킹 힌트나 재색인 필요 여부처럼 함께 달라지는 것이 있다.
    """
    # mode="json"이라야 provider가 enum이 아니라 문자열로 나온다(app_settings.value는 문자열이다).
    updates = request.model_dump(exclude_none=True, mode="json")
    if updates:
        try:
            save_settings(updates, db)
        except ValueError as error:
            # 항목별 형식이 아니라 합친 결과가 성립하지 않는 경우다(예: TEI인데 주소가 없음).
            raise HTTPException(status_code=422, detail=str(error)) from error
    return describe_settings(db)
