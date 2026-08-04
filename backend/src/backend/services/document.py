import hashlib

from loguru import logger
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend.models.document import Document
from backend.schemas.collect import CollectRequest


def document_hash(url: str, content: str) -> str:
    """중복 판정 키. content만으로 해싱하면 본문이 같은 서로 다른 페이지가 한 건으로 뭉개진다.

    특히 본문 추출이 실패해 content가 ''인 페이지들은 전부 sha256('')로 충돌하기 때문에,
    첫 한 건이 그 해시를 선점한 뒤로는 나머지가 모두 조용히 버려졌다. 기사 신디케이션처럼
    본문이 동일한 별개 URL도 마찬가지였다. url을 섞어 같은 URL의 같은 본문만 중복으로 본다.
    """
    return hashlib.sha256(f"{url}\n{content}".encode()).hexdigest()


def save_collected_document(request: CollectRequest, db: Session) -> None:
    """수집한 페이지를 Document로 저장한다. 동일한 (url, content)는 무시한다."""
    content_hash = document_hash(request.url, request.content)
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
        logger.debug("document skipped (same url+content already stored): url={}", request.url)
