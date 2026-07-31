# batch/collect 라우트 서비스 레이어 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `batch.py`, `collect.py` 라우트에 직접 작성된 DB 쿼리/트랜잭션 로직을 `services/` 레이어로 옮겨, `chat.py`가 `services/search.py`를 호출하는 것과 동일한 얇은 라우트 패턴으로 통일한다.

**Architecture:** 기존 로직을 문자 그대로(동작 무변경) 새 서비스 함수로 옮기고, 라우트는 그 함수를 호출해 응답 스키마를 반환하는 한 줄짜리 위임으로 바꾼다. 새 테스트 파일은 추가하지 않으며(스펙에서 결정), 대신 각 단계마다 정적 검증(ruff)과 앱 import 검증으로 배선(wiring) 실수를 잡는다.

**Tech Stack:** FastAPI, SQLAlchemy, sqlite-vec, ruff. 패키지 매니저는 `uv`이지만 이 환경의 PATH에는 없으므로 `.venv/Scripts/python.exe`, `.venv/Scripts/ruff.exe`를 직접 호출한다. `backend` 패키지의 editable install(`​.venv/Lib/site-packages/backend.pth`)이 프로젝트가 이동되기 전 경로(`C:\workspace\앙기모찌\backend\src`)를 가리키고 있어 그냥 import하면 `ModuleNotFoundError: No module named 'backend'`가 난다. 이 플랜의 모든 검증 명령은 `PYTHONPATH=./src`를 함께 지정해 이 문제를 우회한다 (editable install 자체를 고치는 것은 이 플랜의 범위 밖).

**Spec:** `docs/superpowers/specs/2026-07-31-batch-collect-service-layer-design.md`

---

## File Structure

- Create: `src/backend/services/indexing.py` — `batch.py`의 청킹/임베딩/인덱싱 로직을 그대로 이동
- Modify: `src/backend/api/routes/batch.py` — 서비스 호출만 남기고 로직 제거
- Create: `src/backend/services/document.py` — `collect.py`의 해시 계산 + insert 로직을 그대로 이동
- Modify: `src/backend/api/routes/collect.py` — 서비스 호출만 남기고 로직 제거

모든 명령은 `C:\workspace\history_tracker\backend` 디렉터리에서 실행한다.

---

### Task 1: `services/indexing.py` 생성 (batch 로직 이동)

**Files:**
- Create: `src/backend/services/indexing.py`

- [ ] **Step 1: 새 서비스 파일 작성**

`src/backend/api/routes/batch.py`에 있던 SQL 상수와 라우트 함수 본문(트랜잭션 루프)을 그대로 옮긴다. 로직은 한 글자도 바꾸지 않는다 — 함수 이름만 `batch` → `run_indexing_batch`로 바뀌고, `db: Session` 파라미터가 매개변수로 명시된다.

```python
import sqlite_vec
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.models.chunk import Chunk
from backend.models.document import Document
from backend.schemas.batch import BatchResponse
from backend.services.chunking import chunk_text
from backend.services.embedding import embed_texts

INSERT_VEC_CHUNK = text(
    "INSERT INTO vec_chunks (document_id, seq, embedding) VALUES (:document_id, :seq, :embedding)"
)
INSERT_CHUNK_FTS = text("INSERT INTO chunk_fts (vector_key, body) VALUES (:vector_key, :body)")


def run_indexing_batch(db: Session) -> BatchResponse:
    """checked=False인 문서를 청킹/임베딩해 인덱싱하고 결과 통계를 반환한다."""
    documents = db.scalars(select(Document).where(Document.checked.is_(False))).all()

    succeeded = 0
    failed = 0

    for document in documents:
        try:
            with db.begin_nested():
                chunks = chunk_text(document.full_text)
                document.checked = True

                if chunks:
                    embeddings = embed_texts([chunk.text for chunk in chunks])
                    for seq, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                        db.add(
                            Chunk(
                                document_id=document.document_id,
                                seq=seq,
                                char_start=chunk.char_start,
                                char_end=chunk.char_end,
                            )
                        )
                        db.execute(
                            INSERT_VEC_CHUNK,
                            {
                                "document_id": document.document_id,
                                "seq": seq,
                                "embedding": sqlite_vec.serialize_float32(embedding),
                            },
                        )
                        db.execute(
                            INSERT_CHUNK_FTS,
                            {
                                "vector_key": f"{document.document_id}:{seq}",
                                "body": chunk.text,
                            },
                        )
        except Exception:
            failed += 1
        else:
            succeeded += 1

    db.commit()

    return BatchResponse(attempted=len(documents), succeeded=succeeded, failed=failed)
```

- [ ] **Step 2: 정적 검증**

Run: `./.venv/Scripts/ruff.exe check src/backend/services/indexing.py`
Expected: `BLE001 Do not catch blind exception` 경고 1건만 나옴 (원본 `batch.py`에 있던 것과 동일한 기존 이슈이며, 이 리팩토링에서 고치지 않는다). 그 외 새 오류가 없어야 한다.

- [ ] **Step 3: import 검증**

Run: `PYTHONPATH=./src ./.venv/Scripts/python.exe -c "from backend.services.indexing import run_indexing_batch; print('ok')"`
Expected: `ok` 출력, 예외 없음

- [ ] **Step 4: Commit**

```bash
git add src/backend/services/indexing.py
git commit -m "refactor: batch 인덱싱 로직을 services/indexing.py로 이동"
```

---

### Task 2: `routes/batch.py`를 얇은 라우트로 교체

**Files:**
- Modify: `src/backend/api/routes/batch.py` (전체 교체)

- [ ] **Step 1: 라우트 파일 전체를 아래로 교체**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.batch import BatchResponse
from backend.services.indexing import run_indexing_batch

router = APIRouter(tags=["batch"])


@router.post("/batch")
def batch(db: Session = Depends(get_db)) -> BatchResponse:
    return run_indexing_batch(db)
```

- [ ] **Step 2: 정적 검증**

Run: `./.venv/Scripts/ruff.exe check src/backend/api/routes/batch.py`
Expected: `B008 Do not perform function call \`Depends\` in argument defaults` 경고 1건만 나옴 (원본에도 있던 기존 이슈, FastAPI의 표준 패턴이라 고치지 않는다). 그 외 새 오류가 없어야 한다.

- [ ] **Step 3: 앱 전체 import 검증 (라우터 배선 확인)**

Run: `PYTHONPATH=./src ./.venv/Scripts/python.exe -c "from backend.main import app; print(sorted(app.openapi()['paths'].keys()))"`
Expected: 출력 목록에 `/batch`가 포함되고 예외 없음

(참고: 이 venv의 FastAPI 버전은 `app.routes`에 flatten된 `APIRoute`가 아니라 `_IncludedRouter` 래퍼를 담고 있어 `[r.path for r in app.routes]` 형태는 `AttributeError`가 난다 — 리팩토링 이전 코드에서도 동일하게 실패하는 사전 존재 이슈였음을 Task 2 스펙 리뷰에서 확인함. `app.openapi()['paths']`는 이 버전에서도 안정적으로 동작한다.)

- [ ] **Step 4: Commit**

```bash
git add src/backend/api/routes/batch.py
git commit -m "refactor: batch 라우트가 services/indexing.run_indexing_batch만 호출하도록 정리"
```

---

### Task 3: `services/document.py` 생성 (collect 로직 이동)

**Files:**
- Create: `src/backend/services/document.py`

- [ ] **Step 1: 새 서비스 파일 작성**

`src/backend/api/routes/collect.py`에 있던 해시 계산 + insert 로직을 그대로 옮긴다. 함수 이름만 `collect` → `save_collected_document`.

```python
import hashlib

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
    db.execute(stmt)
    db.commit()
```

- [ ] **Step 2: 정적 검증**

Run: `./.venv/Scripts/ruff.exe check src/backend/services/document.py`
Expected: 오류 없음 (원본 `collect.py`에는 없던 이슈이므로 여기서도 0건이어야 한다)

- [ ] **Step 3: import 검증**

Run: `PYTHONPATH=./src ./.venv/Scripts/python.exe -c "from backend.services.document import save_collected_document; print('ok')"`
Expected: `ok` 출력, 예외 없음

- [ ] **Step 4: Commit**

```bash
git add src/backend/services/document.py
git commit -m "refactor: collect 저장 로직을 services/document.py로 이동"
```

---

### Task 4: `routes/collect.py`를 얇은 라우트로 교체

**Files:**
- Modify: `src/backend/api/routes/collect.py` (전체 교체)

- [ ] **Step 1: 라우트 파일 전체를 아래로 교체**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.collect import CollectRequest, CollectResponse
from backend.services.document import save_collected_document

router = APIRouter(tags=["collect"])


@router.post("/collect")
def collect(request: CollectRequest, db: Session = Depends(get_db)) -> CollectResponse:
    save_collected_document(request, db)
    return CollectResponse(status="ok")
```

- [ ] **Step 2: 정적 검증**

Run: `./.venv/Scripts/ruff.exe check src/backend/api/routes/collect.py`
Expected: `B008 Do not perform function call \`Depends\` in argument defaults` 경고 1건만 나옴 (기존 이슈, 원본에도 있었음). 그 외 새 오류가 없어야 한다.

- [ ] **Step 3: 앱 전체 import 검증 (라우터 배선 확인)**

Run: `PYTHONPATH=./src ./.venv/Scripts/python.exe -c "from backend.main import app; print(sorted(app.openapi()['paths'].keys()))"`
Expected: 출력 목록에 `/collect`가 포함되고 예외 없음

(참고: `app.openapi()['paths']` 사용 이유는 Task 2와 동일 — 이 venv의 FastAPI 버전에서 `app.routes`가 flatten된 `APIRoute`를 담고 있지 않아 `[r.path for r in app.routes]`는 `AttributeError`가 난다.)

- [ ] **Step 4: Commit**

```bash
git add src/backend/api/routes/collect.py
git commit -m "refactor: collect 라우트가 services/document.save_collected_document만 호출하도록 정리"
```

---

### Task 5: 전체 회귀 확인

**Files:** 없음 (검증 전용 태스크)

- [ ] **Step 1: 프로젝트 전체 ruff 검사로 새 오류 없는지 확인**

Run: `./.venv/Scripts/ruff.exe check src/backend`
Expected: Task 1~4에서 확인한 기존 이슈(BLE001 1건 in `services/indexing.py`, B008 2건 in `routes/batch.py`/`routes/collect.py`) 외의 새로운 오류가 없어야 한다.

- [ ] **Step 2: 앱 기동 시점 배선 최종 확인**

Run: `PYTHONPATH=./src ./.venv/Scripts/python.exe -c "from backend.main import app; paths = app.openapi()['paths']; assert '/batch' in paths; assert '/collect' in paths; print('wiring ok')"`
Expected: `wiring ok` 출력

- [ ] **Step 3: git status로 의도한 파일만 변경됐는지 확인**

Run: `git status --short`
Expected: 이전 Task들에서 이미 커밋했으므로 untracked/modified 파일이 없어야 한다 (있다면 빠뜨린 커밋이 없는지 확인).
