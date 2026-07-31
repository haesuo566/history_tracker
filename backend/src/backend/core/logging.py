import sys

from loguru import logger

from backend.core.config import settings


def setup_logging() -> None:
    """loguru 로거를 settings.log_level 기준으로 설정한다. 앱 시작 시 한 번만 호출한다."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        ),
    )
