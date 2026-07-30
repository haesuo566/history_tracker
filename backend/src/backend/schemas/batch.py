from pydantic import BaseModel


class BatchResponse(BaseModel):
    attempted: int
    succeeded: int
    failed: int
