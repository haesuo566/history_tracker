from datetime import datetime

from pydantic import BaseModel


class CollectRequest(BaseModel):
    url: str
    title: str
    startTime: datetime
    endTime: datetime
    content: str


class CollectResponse(BaseModel):
    status: str
