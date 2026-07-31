# batch/collect 라우트 서비스 레이어 분리

## 배경
`backend/src/backend/api/routes/batch.py`와 `collect.py`는 DB 쿼리와 트랜잭션 로직을 라우트 함수 안에 직접 작성하고 있다. 반면 `chat.py`는 `services/search.py`의 `search_history()`를 호출하기만 하는 얇은 라우트 구조를 따른다. 일관성을 위해 batch/collect도 동일한 패턴으로 정리한다.

## 범위
- 순수 구조 리팩토링. 기능/동작(로직)은 변경하지 않는다.
- 대상: `api/routes/batch.py`, `api/routes/collect.py`

## 변경 사항

### `services/indexing.py` (신규)
- `batch.py`에 있던 `INSERT_VEC_CHUNK`, `INSERT_CHUNK_FTS` SQL 상수를 이동
- 미처리 문서 조회 → 청킹(`chunk_text`) → 임베딩(`embed_texts`) → `Chunk` 저장 → `vec_chunks`/`chunk_fts` insert → 예외 처리(문서 단위 try/except) → `db.commit()`까지의 로직을 그대로 이동
- 공개 함수: `run_indexing_batch(db: Session) -> BatchResponse`
- `chat.py`가 `search_history()`를 호출해 `ChatResult`를 직접 받는 것과 동일하게, 서비스가 응답 스키마(`BatchResponse`)를 직접 생성해 반환한다.

### `services/document.py` (신규)
- `collect.py`에 있던 content hash 계산(`hashlib.sha256`) + `insert(Document).on_conflict_do_nothing(...)` + `db.commit()` 로직을 그대로 이동
- 공개 함수: `save_collected_document(request: CollectRequest, db: Session) -> None`

### 라우트 (얇아짐)
```python
# batch.py
@router.post("/batch")
def batch(db: Session = Depends(get_db)) -> BatchResponse:
    return run_indexing_batch(db)

# collect.py
@router.post("/collect")
def collect(request: CollectRequest, db: Session = Depends(get_db)) -> CollectResponse:
    save_collected_document(request, db)
    return CollectResponse(status="ok")
```

## 테스트
- 기존 동작을 그대로 옮기는 리팩토링이므로 새 테스트 케이스는 추가하지 않는다.
- 기존 테스트가 있다면 리팩토링 후에도 통과해야 한다 (동작 무변경 확인용 회귀 검증).

## 비범위 (Out of scope)
- 로직/동작 개선 (예: batch의 예외 처리 방식, collect의 응답값 등) — 사용자가 순수 구조 리팩토링만 원한다고 확인함
- `chat.py`/`services/search.py`는 이미 목표 패턴을 따르고 있어 변경하지 않음
