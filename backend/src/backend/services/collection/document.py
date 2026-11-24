import hashlib

from loguru import logger
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend.models.document import Document
from backend.schemas.collect import CollectRequest


def document_hash(url: str) -> str:
    """중복 판정 키. URL 하나가 문서 하나다.

    본문을 섞어 해싱하던 옛 방식(`sha256(url + content)`)은 같은 URL을 다시 방문할 때마다 새
    문서를 쌓았다. 광고·추천 목록·조회수처럼 본문 추출에 딸려 들어오는 자리가 방문마다 조금씩
    달라서, 실제로는 같은 페이지인데 검색 결과를 여러 행이 나눠 차지했다.

    그 대가로 **처음 수집한 본문이 그대로 굳는다.** 내용이 갱신된 기사를 다시 방문해도 예전
    본문이 남고, 첫 수집이 빈 본문이었다면 그 URL은 계속 빈 채로 남는다. 최신 본문으로
    덮어쓰려면 이미 쌓인 그 문서의 청크·벡터·전문 색인까지 함께 버려야 해서 택하지 않았다.

    content를 아예 빼도 옛 주석이 걱정한 두 가지는 생기지 않는다. 본문 추출이 실패한 페이지들이
    `sha256('')`로 충돌하던 문제도, 본문이 같은 별개 URL이 한 건으로 뭉개지던 문제도 모두
    "본문이 해시에 들어가는 것" 자체가 원인이었다.
    """
    return hashlib.sha256(url.encode()).hexdigest()


def save_collected_document(request: CollectRequest, db: Session) -> None:
    """수집한 페이지를 Document로 저장한다. 이미 있는 url은 무시한다."""
    content_hash = document_hash(request.url)
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
    result = db.execute(stmt)
    db.commit()

    if result.rowcount:
        logger.info("document saved: url={} title={}", request.url, request.title)
    else:
        logger.debug("document skipped (url already stored): url={}", request.url)
