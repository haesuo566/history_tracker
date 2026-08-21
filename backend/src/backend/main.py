import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from backend.api.routes import batch, chat, collect, conversation, health, reindex
from backend.api.routes import settings as settings_route
from backend.core.config import settings
from backend.core.logging import setup_logging
from backend.db.init_db import init_db

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "{method} {path} -> {status} ({duration:.1f}ms)",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration=duration_ms,
    )
    return response

app.include_router(health.router)
app.include_router(collect.router)
app.include_router(batch.router)
app.include_router(chat.router)
app.include_router(conversation.router)
app.include_router(settings_route.router)
app.include_router(reindex.router)
