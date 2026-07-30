from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Chunk(Base):
    __tablename__ = "chunks"

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.document_id"), primary_key=True)
    seq: Mapped[int] = mapped_column(primary_key=True)
    char_start: Mapped[int]
    char_end: Mapped[int]
