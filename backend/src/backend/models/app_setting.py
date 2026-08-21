from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class AppSetting(Base):
    """운영 중에 바꿀 수 있는 설정 한 항목.

    .env(core.config.Settings)는 기동 시점에 고정되므로 화면에서 바꿀 수 없다. 여기 저장된 값이
    있으면 .env 값보다 우선한다(services.runtime_settings). 항목마다 컬럼을 두지 않고 key/value로
    두는 것은 설정을 더할 때 스키마 마이그레이션이 필요 없게 하려는 것이다 — 이 프로젝트에는
    마이그레이션 도구가 없다(db.init_db._ensure_column 주석 참고).
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
