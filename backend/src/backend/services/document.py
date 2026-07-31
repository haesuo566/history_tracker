import hashlib

from loguru import logger
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend.models.document import Document
from backend.schemas.collect import CollectRequest


def save_collected_document(request: CollectRequest, db: Session) -> None:
    """수집한 페이지를 Document로 저장한다. 동일한 content(hash 기준)는 무시한다."""
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
    result = db.execute(stmt)
    db.commit()

    if result.rowcount:
        logger.info("document saved: url={} title={}", request.url, request.title)
    else:
        logger.debug("document skipped (duplicate content): url={}", request.url)
