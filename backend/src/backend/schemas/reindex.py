from pydantic import BaseModel


class ReindexResponse(BaseModel):
    """POST /reindex 결과.

    색인을 비우기만 하고 다시 쌓지는 않는다. pending에 담긴 문서를 실제로 채우는 것은 기존
    색인 배치(POST /batch)다 — 문서가 많으면 임베딩에 분 단위가 걸려 한 요청 안에서 끝낼 수 없다.
    """

    provider: str
    dim: int
    # 앞으로 청크 하나에 담을 문자 수. 임베딩의 입력 한계에서 환산한 값이다.
    chunk_chars: int
    # 이번에 색인을 다시 쌓아야 하는 문서 수(= 색인 대기로 되돌린 문서 수).
    pending: int
    # 차원이 바뀌어 vec_chunks를 다시 만들었는지. 같은 차원이면 테이블은 그대로 두고 내용만 비운다.
    recreated: bool
