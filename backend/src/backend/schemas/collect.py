from datetime import datetime

from pydantic import BaseModel


class CollectRequest(BaseModel):
    """확장이 본문 추출 직후 보내는 수집 레코드.

    체류시간을 쓰지 않게 되면서 endTime 필드가 사라졌다. 구버전 확장의 재시도 큐에 남아
    나중에 올라오는 레코드는 endTime을 싣고 있는데, pydantic이 미정의 필드를 무시하므로
    그대로 받아들여진다.
    """

    url: str
    title: str
    startTime: datetime
    content: str


class CollectResponse(BaseModel):
    status: str
