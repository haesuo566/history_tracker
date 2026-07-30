from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(unique=True, index=True, default=lambda: str(uuid4()))
    url: Mapped[str]
    title: Mapped[str]
    full_text: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    checked: Mapped[bool] = mapped_column(default=False)
