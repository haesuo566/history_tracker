# history_tracker

내가 본 웹페이지를 자동으로 모아두고, 나중에 자연어로 다시 찾는 도구.

"어제 본 리액트 상태관리 글" 처럼 기억나는 대로 물어보면, 방문 기록 중 가장 관련 있는
페이지 한 건을 링크로 돌려줍니다. 제목·URL 뿐 아니라 **본문 내용까지 색인**하기 때문에
브라우저 기본 방문 기록 검색으로는 못 찾는 페이지도 찾을 수 있습니다.

## 구성

세 개의 독립된 컴포넌트로 나뉩니다.

| 디렉터리 | 역할 | 스택 |
| --- | --- | --- |
| [`extension/`](extension/README.md) | 방문 페이지 수집 (Chrome 확장) | Manifest V3, Mozilla Readability |
| `backend/` | 저장 · 색인 · 하이브리드 검색 | FastAPI, SQLAlchemy, SQLite(vec0 + FTS5), Gemini |
| [`frontend/`](frontend/README.md) | 검색용 채팅 UI | Next.js 16 App Router, React 19, Tailwind 4 |

### 데이터 흐름

```
[Chrome 확장]  방문 종료 시점에 즉시 전송
     │  POST /collect  { url, title, startTime, endTime, content }
     ▼
[documents]  본문 SHA-256 해시로 중복 제거, checked = false 로 적재
     │
     │  POST /batch  (수동 트리거 — 프론트엔드의 색인 버튼 또는 직접 호출)
     ▼
청킹(약 2048토큰, 개행 경계) → Gemini 임베딩 → [chunks] + [vec_chunks] + [chunk_fts]
     │
     │  POST /chat  { message: "어제 본 리액트 글" }
     ▼
질의 재작성(Gemini) ─┬─ 임베딩 → vec_chunks 벡터 검색 (k=5)
                     └─ Kiwi 명사 추출 → chunk_fts 전문 검색 (FTS5)
                                │
                     RRF(k=60) 병합 → 문서별 최고 점수 → 1위 문서 1건 반환
```

수집(`/collect`)과 색인(`/batch`)이 분리되어 있습니다. 수집은 방문할 때마다 실시간으로
일어나지만, 임베딩 API 호출은 비용이 있으므로 미처리 문서를 모아 배치로 처리합니다.

## 빠른 시작

### 1. 백엔드

```bash
cd backend
uv sync
```

`backend/.env` 에 Gemini API 키를 넣습니다.

```
GEMINI_API_KEY=your-api-key
```

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Google AI Studio 에서 발급 |
| `DATABASE_URL` | `sqlite:///./app.db` | SQLite 이외를 쓰면 `vec_chunks`/`chunk_fts` 가 생성되지 않습니다 |
| `EMBEDDING_DIM` | `3072` | 색인 후 변경하면 기존 벡터와 차원이 어긋납니다 |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | |
| `QUERY_REWRITE_MODEL` | `gemini-3.5-flash` | 질의 재작성용 |

서버를 띄웁니다. 첫 실행 시 테이블과 가상 테이블이 자동 생성됩니다.

```bash
uv run uvicorn backend.main:app --reload
```

`http://127.0.0.1:8000/docs` 에서 API 문서를 볼 수 있습니다.

### 2. Chrome 확장

1. `chrome://extensions` → 우측 상단 "개발자 모드" 켜기
2. "압축해제된 확장 프로그램을 로드합니다" → `extension` 폴더 선택
3. 확장 아이콘 → "설정 열기" → API 서버 주소(`http://127.0.0.1:8000`)와 최소 체류시간 저장

설정값과 제약은 [`extension/README.md`](extension/README.md) 참고.

### 3. 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

http://localhost:3000 접속. 백엔드 주소가 기본값(`http://127.0.0.1:8000`)과 다르면
`.env.local` 에 `BACKEND_URL` 을 넣습니다.

### 4. 사용

몇 개 페이지를 돌아다녀 문서를 모은 뒤, 화면의 색인 버튼으로 `/batch` 를 한 번 실행하고
질문하면 됩니다. 색인하지 않은 문서는 검색되지 않습니다.

## API

| 메서드 | 경로 | 요청 | 응답 |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `{ "status": "ok" }` |
| `POST` | `/collect` | `url`, `title`, `startTime`, `endTime`, `content` | `{ "status": "ok" }` |
| `POST` | `/batch` | 없음 | `{ "attempted": 3, "succeeded": 3, "failed": 0 }` |
| `POST` | `/chat` | `{ "message": "...", "conversation_id": "..." \| null }` | `{ conversation_id, results: [{ document_id, url, title, score, snippet }], answer }` |
| `GET` | `/conversations` | `limit` (기본 50, 최대 200) | `{ "conversations": [{ conversation_id, title, message_count, created_at, last_message_at }] }` |
| `GET` | `/conversations/{conversation_id}` | — | `{ conversation_id, created_at, messages: [{ role, content, created_at }] }`, 모르는 id 면 `404` |
| `DELETE` | `/conversations/{conversation_id}` | — | `204`, 모르는 id 면 `404` |

`/batch` 는 문서 단위로 savepoint 를 잡기 때문에 한 문서의 색인이 실패해도 나머지는
그대로 커밋됩니다. 실패한 문서는 `checked` 가 `false` 로 남아 다음 실행에서 재시도됩니다.

`/chat` 은 `conversation_id` 없이 부르면 대화를 알아서 열고 그 id 를 응답에 담아 주므로,
클라이언트는 그 값을 저장해뒀다가 다음 요청에 실어 보내면 대화가 이어집니다.

`title` 은 그 대화의 첫 `user` 메시지를 한 줄로 접어 60자까지 자른 뒤 `conversations.title` 에
저장된 값입니다. 그 메시지가 저장되는 시점에 한 번만 채워지고 이후로는 바뀌지 않으므로, 매 목록
조회마다 `messages` 를 다시 훑지 않습니다(`message_count`, `last_message_at` 은 컬럼으로 두지
않아 여전히 그때마다 집계합니다). 정렬은 최근 활동 순이며, 시각이 초 단위라 같은 초에 몰린
대화끼리는 id 로 갈립니다.

`DELETE /conversations/{conversation_id}` 는 대화와 그 메시지를 함께 지웁니다. `Message.conversation_id`
가 FK 로 선언돼 있지만 SQLite 는 `PRAGMA foreign_keys=ON` 없이는 이를 강제하지 않고, 이 프로젝트도
그 설정을 켜지 않으므로 메시지를 명시적으로 같이 지웁니다.

## 저장 구조

| 테이블 | 종류 | 내용 |
| --- | --- | --- |
| `documents` | 일반 | 수집 원본. `document_id`(UUID), `url`, `title`, `full_text`, `hash`, `timestamp`, `checked` |
| `chunks` | 일반 | 청크의 원문 위치. `(document_id, seq)` 복합 PK, `char_start`, `char_end` |
| `vec_chunks` | vec0 가상 | 청크 임베딩. `document_id` 를 파티션 키로 사용 |
| `chunk_fts` | FTS5 가상 | 청크 본문 전문 색인. `vector_key` 는 `"{document_id}:{seq}"` |
| `conversations` | 일반 | 대화 세션. `conversation_id`(UUID), `created_at`, `title`(첫 user 메시지에서 한 번만 채워지는 캐시, 최대 61자) |
| `messages` | 일반 | 대화에 오간 메시지. `conversation_id`, `role`, `content`. 순서는 `id` 로 판단합니다 |

청크 본문은 `chunks` 에 중복 저장하지 않고 `char_start`/`char_end` 로 `documents.full_text`
를 가리킵니다. 전문 검색용 사본만 `chunk_fts` 에 들어갑니다.

### 왜 하이브리드 검색인가

벡터 검색만 쓰면 "리액트 훅" 같은 고유명사·전문용어가 의미적으로 뭉개지고, 전문 검색만
쓰면 표현이 다른 질문("상태관리 어떻게 하는지 본 글")을 놓칩니다. 두 결과를 순위
기반(RRF)으로 합치면 점수 스케일이 다른 두 검색을 정규화 없이 섞을 수 있습니다.
한국어는 조사가 붙어 FTS5 토크나이저와 잘 맞지 않으므로, Kiwi 형태소 분석으로 명사만
뽑아 `OR` 질의로 만듭니다.

## 개발

```bash
# 백엔드
cd backend
uv run ruff check .
uv run ruff format .
uv run pytest

# 프론트엔드
cd frontend
npm run lint
npx tsc --noEmit
```

Python 3.12 이상이 필요합니다(`backend/.python-version`).

## 알려진 제약

- **검색 결과는 항상 1건**입니다. `/chat` 은 RRF 1위 문서만 반환하며, 관련 기록이 없으면
  `result: null` 입니다.
- **`/batch` 는 자동 실행되지 않습니다.** 스케줄러가 없어 색인 시점을 직접 골라야 합니다.
- **CORS 가 전면 개방**되어 있습니다(`allow_origins=["*"]`). 확장 프로그램에서 직접
  호출하기 위한 설정이므로, 로컬 또는 신뢰된 네트워크 안에서만 띄우세요.
- **인증이 없습니다.** 열린 네트워크에 노출하면 누구나 방문 기록을 조회·삽입할 수 있습니다.
- **마이그레이션 도구가 없습니다.** 스키마는 `Base.metadata.create_all` 로만 생성되므로,
  이는 이미 있는 테이블에 컬럼을 더해주지 않습니다. 대부분의 모델 변경은 기존 DB(`app.db`)를
  지우고 다시 만들어야 합니다. 컬럼을 추가하는 경우처럼 기존 데이터(수집한 문서·임베딩 등,
  다시 만들려면 비용이 들거나 재수집이 불가능한 데이터)를 지킬 필요가 있으면, `init_db()`
  안에서 `PRAGMA table_info` 로 존재 여부를 확인하고 없을 때만 `ALTER TABLE` 로 더하는 식의
  1회성 마이그레이션을 직접 추가해야 합니다(`conversations.title` 이 그 사례입니다).
- 확장 프로그램 쪽 제약(시크릿 모드, SPA 본문 재추출)은
  [`extension/README.md`](extension/README.md) 에 정리되어 있습니다.
