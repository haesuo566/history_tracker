# history_tracker

내가 본 웹페이지를 자동으로 모아두고, 나중에 자연어로 다시 찾는 도구.

"어제 본 리액트 상태관리 글" 처럼 기억나는 대로 물어보면, 방문 기록에서 관련 있는 페이지를
찾아 링크 카드와 답변을 함께 돌려줍니다. 제목·URL 뿐 아니라 **본문 내용까지 색인**하기 때문에
브라우저 기본 방문 기록 검색으로는 못 찾는 페이지도 찾을 수 있습니다.

찾아준 결과 중 하나를 "두 번째 것 자세히 알려줘", "velog에서 본 거 요약해줘" 처럼 지목하면
그 페이지의 **본문을 근거로** 요약하거나 물은 대목을 찾아 답합니다. 대화는 세션으로 남아
이어서 물을 수 있고, 사이드바에서 지난 대화를 다시 열 수 있습니다.

## 구성

세 개의 독립된 컴포넌트로 나뉩니다.

| 디렉터리 | 역할 | 스택 |
| --- | --- | --- |
| [`extension/`](extension/README.md) | 방문 페이지 수집 (Chrome 확장) | Manifest V3, Mozilla Readability |
| `backend/` | 저장 · 색인 · 하이브리드 검색 | FastAPI, SQLAlchemy, SQLite(vec0 + FTS5), Gemini, TEI(선택) |
| [`frontend/`](frontend/README.md) | 검색용 채팅 UI, 대화 목록, 색인 트리거 | Next.js 16 App Router, React 19, Tailwind 4 |

### 데이터 흐름

```
[Chrome 확장]  본문 추출 직후 즉시 전송
     │  POST /collect  { url, title, startTime, content }
     ▼
[documents]  URL SHA-256 해시로 중복 제거(URL 하나 = 문서 하나), checked = false 로 적재
     │
     │  POST /batch  (수동 트리거 — 프론트엔드의 색인 버튼 또는 직접 호출)
     ▼
청킹(임베딩 입력 한계에 맞춰 자동, 개행 경계) → 임베딩(Gemini 또는 TEI)
     → [chunks] + [vec_chunks] + [chunk_fts]
     │
     │  POST /chat  { message: "어제 본 리액트 글" }
     ▼
전처리: 대화 확정·입력 저장 → 직전 대화 + 직전에 보여준 결과 목록을 맥락으로
        의도 판단 + 질의 재작성 + 지목 대상 번호를 한 번에 받음 (Gemini 1회)
     │
     ├─ etc     잡담. 검색 없이 일반 응답
     │
     ├─ detail  이미 보여준 결과 중 하나를 지목한 턴. 그 문서의 본문을 근거로 답변
     │          (어느 것인지 특정하지 못하면 recall 로 내려보냄)
     │
     └─ recall  기록을 새로 검색
            │
            ├─ 임베딩 → vec_chunks 벡터 검색 (최근접 50건, 유사도 하한 이내)
            └─ Kiwi 명사 추출 → chunk_fts 전문 검색 (FTS5)
                       │
            RRF(k=60) 병합 → 문서별 최고 점수 → 상위 N건 반환
            (N은 기본 5, "3개만" 처럼 요청하면 그 개수)
```

수집(`/collect`)과 색인(`/batch`)이 분리되어 있습니다. 수집은 방문할 때마다 실시간으로
일어나지만, 임베딩 API 호출은 비용이 있으므로 미처리 문서를 모아 배치로 처리합니다.

각 단계는 그림과 함께 따로 정리해두었습니다.

- [`docs/collection-pipeline.md`](docs/collection-pipeline.md) — 방문을 어떤 기준으로 잡아 본문을
  추출하고 어떻게 색인까지 쌓는지
- [`docs/query-flow.md`](docs/query-flow.md) — 질문 한 건이 들어와 답변과 링크 카드가 나가기까지

## 빠른 시작

### 1. 백엔드

```bash
cd backend
uv sync
```

`.env.example` 을 복사해 `backend/.env` 를 만들고 Gemini API 키를 채웁니다.

```bash
cp .env.example .env
```

설정값은 전부 `.env` 에서 읽습니다. 코드에 기본값이 없으므로 아래 항목이 하나라도
비어 있으면 서버가 뜨지 않습니다.

★ 표시한 네 항목은 [설정 화면](#5-설정)에서 재기동 없이 바꿀 수 있고, 한 번 저장하면 그 값이
`.env` 보다 우선합니다. 나머지는 `.env` 전용입니다.

| 환경변수 | 예시값 | 설명 |
| --- | --- | --- |
| `APP_NAME` | `backend` | FastAPI 문서 제목 |
| `LOG_LEVEL` | `INFO` | loguru 로그 레벨 |
| `GEMINI_API_KEY` ★ | — | Google AI Studio 에서 발급 |
| `DATABASE_URL` | `sqlite:///./app.db` | SQLite 이외를 쓰면 `vec_chunks`/`chunk_fts` 가 생성되지 않습니다 |
| `EMBEDDING_DIM` | `3072` | 색인 후 변경하면 기존 벡터와 차원이 어긋납니다 |
| `EMBEDDING_MODEL` ★ | `gemini-embedding-001` | |
| `QUERY_REWRITE_MODEL` ★ | `gemini-3.1-flash-lite` | 질의 재작성·의도 판단용 |
| `ANSWER_MODEL` ★ | `gemini-3.1-flash-lite` | 답변 생성용 |
| `MIN_COSINE_SIMILARITY` | `0.5` | 벡터 검색 최소 유사도 |
| `MIN_FTS_MATCHED_TERMS` | `1` | FTS 검색 최소 일치 명사 수 |
| `CHAT_HISTORY_MESSAGES` | `30` | 프롬프트에 넣을 직전 대화 개수 |
| `CHAT_HISTORY_MAX_CHARS` | `8000` | 직전 대화의 글자 수 상한. 넘치면 오래된 것부터 버립니다 |
| `DETAIL_MAX_CHARS` | `20000` | 상세 답변의 근거로 실을 본문 길이 상한. 넘치면 앞부분만 씁니다 |

서버를 띄웁니다. 첫 실행 시 테이블과 가상 테이블이 자동 생성됩니다.

```bash
uv run uvicorn backend.main:app --reload
```

`http://127.0.0.1:8000/docs` 에서 API 문서를 볼 수 있습니다.

### 2. Chrome 확장

1. `chrome://extensions` → 우측 상단 "개발자 모드" 켜기
2. "압축해제된 확장 프로그램을 로드합니다" → `extension` 폴더 선택
3. 확장 아이콘 → "설정 열기" → API 서버 주소(`http://127.0.0.1:8000`) 저장

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

### 5. 설정

화면 우측 상단의 톱니바퀴(`/settings`)에서 모델과 Gemini API key, 임베딩 제공자를 바꿉니다.
저장한 값은 `app_settings` 테이블에 남아 `.env` 보다 우선하고, 서버를 다시 띄우지 않아도 다음
요청부터 적용됩니다.

- 고를 수 있는 모델은 백엔드 상수(`core/model_catalog.py`)에 적힌 목록입니다. 여기 없는 모델을
  쓰려면 `.env` 로 지정하세요 — 그 값도 `(.env 지정)` 이 붙어 선택 상자에 함께 나옵니다.
- API key 는 저장 후 원문을 되돌려주지 않습니다. 끝 네 자리 힌트만 보이고, 입력란을 비워 두고
  저장하면 기존 키가 유지됩니다.

설정 변경은 프로세스 안의 캐시를 갱신하는 방식이라, 워커를 여러 개 띄우면 변경을 받지 못한
워커가 남습니다. 즉시 반영이 필요하면 단일 워커로 띄우세요.

### 6. 임베딩 제공자 (Gemini 또는 TEI)

임베딩은 Gemini API 대신 자체 호스팅 [TEI](https://github.com/huggingface/text-embeddings-inference)
로 받을 수 있습니다. 답변 생성과 질의 재작성은 그대로 Gemini 를 쓰므로 API key 는 여전히
필요합니다. 임베딩만 밖으로 내보내지 않게 되는 것입니다.

TEI 를 띄웁니다(예: bge-m3).

```bash
docker run -p 8080:80 --gpus all \
  ghcr.io/huggingface/text-embeddings-inference:latest \
  --model-id BAAI/bge-m3
```

설정 화면에서 제공자를 'TEI' 로 바꾸고 주소(`http://127.0.0.1:8080`)를 넣어 저장한 뒤,
**색인을 다시 만들어야** 합니다. 저장만 하면 검색은 본문 단어 검색만으로 동작합니다.

호출은 OpenAI 호환 경로(`POST /v1/embeddings`)로 나갑니다. 그래서 vLLM·Infinity 처럼 같은 규약을
내놓는 서버도 그대로 붙습니다. 주소에 `/v1/embeddings` 를 붙여 적어도 되고 생략해도 됩니다.

#### 왜 재색인이 필요한가

임베딩을 바꾸면 이미 쌓인 벡터는 **다른 공간의 좌표**가 되어 검색에 쓸 수 없습니다. 차원까지
달라지면(gemini-embedding-001 은 3072, bge-m3 는 1024) `vec_chunks` 자체를 그 차원으로 다시
만들어야 합니다 — 가상 테이블에는 차원을 바꾸는 `ALTER` 가 없습니다.

그래서 백엔드는 색인이 어떤 임베딩으로 만들어졌는지 서명(`제공자:모델`)으로 남겨 두고, 지금
설정과 다르면 `/settings` 응답의 `reindex_required` 를 켭니다. 그동안 검색은 **벡터 검색을 건너뛰고
전문 검색만** 씁니다. 차원이 어긋난 채로 벡터 검색을 하면 sqlite-vec 가 오류를 내며 검색 전체가
실패하고, 차원이 같아도 값이 무의미해 엉뚱한 문서가 올라옵니다.

`POST /reindex` (화면의 '색인 다시 만들기') 는 색인을 비우기만 합니다.

| 지워지는 것 | 남는 것 |
| --- | --- |
| `chunks`, `vec_chunks`, `chunk_fts` | `documents` (수집한 본문), `conversations`, `messages` |

`documents` 를 남기는 것은 수집이 확장이 방문할 때만 일어나 다시 만들 수 없기 때문입니다. 청크와
벡터는 본문만 있으면 언제든 다시 만들 수 있습니다. 비운 뒤 모든 문서가 색인 대기로 돌아가므로,
이어서 색인 버튼(`POST /batch`)을 눌러 다시 쌓습니다. 기록 수만큼 임베딩 호출이 듭니다.

차원을 알아내려고 임베딩을 한 번 호출하는 것이 재색인의 첫 단계입니다. TEI 에 붙지 못하면 그
지점에서 실패하고 색인은 그대로 남습니다 — 되돌릴 수 없는 일을 하기 전에 막습니다.

#### 청킹 크기는 임베딩이 정합니다

청크 하나의 크기는 설정 항목이 아닙니다. **지금 쓰는 임베딩의 입력 한계에서 자동으로 환산**합니다.

| 임베딩 | 입력 한계 | 청크 크기 |
| --- | --- | --- |
| `gemini-embedding-001` | 2048 토큰 | 2252자 |
| `gemini-embedding-2` | 8192 토큰 | 9011자 |
| TEI | `/info` 의 `max_input_length` | 그 값 × 1.1 |

한계를 넘겨 보내면 **오류가 나지 않고 뒷부분이 조용히 버려집니다**. Gemini 도 TEI 도 그렇습니다
(TEI 는 `auto_truncate` 가 기본으로 켜져 있습니다). 그래서 사람이 숫자를 적어 넣는 방식으로 두지
않았습니다 — 잘못 적으면 색인이 성공한 것처럼 보이면서 검색 품질만 떨어집니다.

토큰이 아니라 문자로 자르는 것은 임베딩 모델의 토크나이저를 로컬에서 돌릴 수 없기 때문입니다.
대신 토큰 한계를 **1토큰 = 1.1자**로 보수적으로 환산합니다(`core/model_catalog.py`). 실제 수집된
한국어 문서를 재보면 1.22~3.89 자/토큰이고, 가장 촘촘한 문서에서도 한계의 90% 안에 들어옵니다.
한국어는 영어(3~4자/토큰)보다 훨씬 촘촘해서, 넉넉하게 잡으면 그만큼 뒤가 잘려 나갑니다.

TEI 가 `/info` 를 내놓지 않으면 보수적으로 512 토큰(TEI 기본값)으로 봅니다. 청크가 짧아질 뿐
잘리지는 않습니다.

청킹 기준도 색인 상태에 남습니다. 그래서 임베딩을 바꿔 청크 크기가 달라지면 설정 화면이 재색인을
안내합니다. 이때 **벡터 검색은 계속 동작합니다** — 좌표를 만든 모델이 같으므로 견줄 수는 있고,
한계를 넘겼던 부분이 빠져 있을 뿐입니다. 모델 자체가 바뀐 경우(벡터를 쓸 수 없는 경우)와는 화면
안내가 다릅니다.

#### 모델을 고를 때

`EMBEDDING_DIM` 은 Gemini 경로에서 요청하는 차원이고, TEI 차원은 서버에 올린 모델이 정합니다.
지금 색인의 차원과 청크 크기는 설정 화면에 표시됩니다.

bge-m3 를 기준으로 맞춰 두었습니다. 다른 모델을 쓸 때 걸리는 것:

- **query/passage 프리픽스** — Gemini 는 문서와 질의를 다른 `task_type` 으로 임베딩하지만 TEI 에는
  그 개념이 없습니다. e5 계열은 `query: `/`passage: ` 프리픽스가 그 역할을 하는데, bge-m3 는
  요구하지 않으므로 지금은 문서와 질의를 같은 방식으로 보냅니다.
- **배치 크기** — TEI 의 `--max-client-batch-size` 기본값이 32라 청크를 32개씩 잘라 보냅니다.

## API

| 메서드 | 경로 | 요청 | 응답 |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `{ "status": "ok" }` |
| `POST` | `/collect` | `url`, `title`, `startTime`, `content` | `{ "status": "ok" }` |
| `POST` | `/batch` | 없음 | `{ "attempted": 3, "succeeded": 3, "failed": 0 }` |
| `POST` | `/chat` | `{ "message": "...", "conversation_id": "..." \| null }` | `{ conversation_id, results: [{ document_id, url, title, score, snippet }], answer }` |
| `GET` | `/conversations` | `limit` (기본 50, 최대 200) | `{ "conversations": [{ conversation_id, title, message_count, created_at, last_message_at }] }` |
| `GET` | `/conversations/{conversation_id}` | — | `{ conversation_id, created_at, messages: [{ role, content, created_at }] }`, 모르는 id 면 `404` |
| `PATCH` | `/conversations/{conversation_id}` | `{ "title": "..." }` | `204`, 모르는 id 면 `404`, 빈 문자열이거나 60자를 넘는 `title` 이면 `422` |
| `DELETE` | `/conversations/{conversation_id}` | — | `204`, 모르는 id 면 `404` |
| `GET` | `/settings` | — | 지금 설정과 선택지. 모델 3종, `embedding_provider`, `tei_base_url`, `tei_model`, `embedding_dim`, `indexed_dim`, `reindex_required`, `api_key_configured`, `api_key_hint`, 선택지 목록 |
| `PATCH` | `/settings` | 모델 3종, `embedding_provider`, `tei_base_url`, `tei_model`, `gemini_api_key` 중 바꿀 것만 | `GET` 과 같은 형태의 갱신 결과. 목록 밖 모델·빈 `gemini_api_key`·주소 없는 `tei` 면 `422` |
| `POST` | `/reindex` | 없음 | `{ "provider": "tei", "dim": 1024, "pending": 12, "recreated": true }`. 임베딩 제공자에 붙지 못하면 `502` 이고 색인은 그대로 |

`/batch` 는 문서 단위로 savepoint 를 잡기 때문에 한 문서의 색인이 실패해도 나머지는
그대로 커밋됩니다. 실패한 문서는 `checked` 가 `false` 로 남아 다음 실행에서 재시도됩니다.

`/chat` 은 `conversation_id` 없이 부르면 대화를 알아서 열고 그 id 를 응답에 담아 주므로,
클라이언트는 그 값을 저장해뒀다가 다음 요청에 실어 보내면 대화가 이어집니다.

`title` 은 그 대화의 첫 `user` 메시지를 한 줄로 접어 60자까지 자른 뒤 `conversations.title` 에
저장된 값입니다. 그 메시지가 저장되는 시점에 한 번만 채워지므로, 매 목록 조회마다 `messages` 를
다시 훑지 않습니다(`message_count`, `last_message_at` 은 컬럼으로 두지 않아 여전히 그때마다
집계합니다). 이후 자동으로 바뀌는 일은 없고, `PATCH /conversations/{conversation_id}` 로만
바뀝니다. 정렬은 최근 활동 순이며, 시각이 초 단위라 같은 초에 몰린 대화끼리는 id 로 갈립니다.

`DELETE /conversations/{conversation_id}` 는 대화와 그 메시지를 함께 지웁니다. `Message.conversation_id`
가 FK 로 선언돼 있지만 SQLite 는 `PRAGMA foreign_keys=ON` 없이는 이를 강제하지 않고, 이 프로젝트도
그 설정을 켜지 않으므로 메시지를 명시적으로 같이 지웁니다.

## 의도 분류

`/chat` 은 한 턴을 세 갈래로 봅니다.

| 의도 | 뜻 | 답변 근거 |
| --- | --- | --- |
| `recall` | 기록에서 페이지를 새로 찾는 질문 | 검색 결과 목록(제목·URL·본문 발췌) |
| `detail` | 이미 찾아준 결과 중 하나를 지목해 더 캐묻는 질문 | 지목된 문서 하나의 본문 |
| `etc` | 잡담이나 무관한 질문 | 없음(일반 대화) |

먼저 정규식으로 확실한 것만 가릅니다. 인사말은 `etc`, "찾아줘"·"봤던 사이트" 같은 표현은
`recall` 입니다. 정규식은 `detail` 을 판정하지 않습니다 — 같은 표현이 새로 찾는 질문과 이미
찾아준 결과를 캐묻는 질문에 똑같이 붙어, 앞선 대화를 봐야 갈리기 때문입니다.

나머지는 질의 재작성 호출이 판단합니다. 지시 표현("그거", "아까 그 사이트")이 무엇을 가리키는지
찾는 일과 이 턴이 `recall` 인지 판단하는 일이 같은 추론이라, 의도·검색어·지목 대상 번호·요청
개수를 한 번의 호출로 함께 받습니다.

지목한 문서를 특정하는 것은 두 단계입니다. 1차는 이 호출이 후보 목록을 보고 고른 번호로,
순서("두 번째")·제목·사이트 이름이 한 번에 풀립니다. 2차는 그 번호가 없거나 범위를 벗어났을
때의 문자열 매칭(명사 겹침 + 유사도)입니다. 둘 다 실패하면 아무거나 고르지 않고 `recall` 로
내려보냅니다. 엉뚱한 문서를 근거로 그럴듯하게 답하는 것이 가장 나쁜 실패라서입니다.

## 저장 구조

| 테이블 | 종류 | 내용 |
| --- | --- | --- |
| `documents` | 일반 | 수집 원본. `document_id`(UUID), `url`, `title`, `full_text`, `hash`, `timestamp`, `checked` |
| `chunks` | 일반 | 청크의 원문 위치. `(document_id, seq)` 복합 PK, `char_start`, `char_end` |
| `vec_chunks` | vec0 가상 | 청크 임베딩. `document_id` 를 파티션 키로 사용 |
| `chunk_fts` | FTS5 가상 | 청크 본문 전문 색인. `vector_key` 는 `"{document_id}:{seq}"` |
| `conversations` | 일반 | 대화 세션. `conversation_id`(UUID), `created_at`, `title`(첫 user 메시지에서 한 번만 채워지는 캐시, 최대 61자) |
| `messages` | 일반 | 대화에 오간 메시지. `conversation_id`, `role`, `content`, `result_document_ids`(그 턴에 보여준 결과의 문서 id 목록. 결과가 없던 턴은 `NULL`). 순서는 `id` 로 판단합니다 |
| `app_settings` | 일반 | 설정 화면에서 바꾼 값. `key` PK, `value`, `updated_at`. 여기 있는 항목만 `.env` 를 덮어씁니다. 색인이 어떤 임베딩으로 만들어졌는지(`indexed_embedding_dim`, `indexed_embedding_signature`)도 여기 남고, 그쪽은 재색인만 씁니다 |

청크 본문은 `chunks` 에 중복 저장하지 않고 `char_start`/`char_end` 로 `documents.full_text`
를 가리킵니다. 전문 검색용 사본만 `chunk_fts` 에 들어갑니다.

`messages.result_document_ids` 는 "두 번째 것" 같은 지목을 풀기 위한 것입니다. `content` 에는
답변 문장만 남아 제목이 실리지 않은 턴은 무엇을 보여줬는지 되짚을 수 없으므로, 보여준 순서대로
문서 id 를 따로 남깁니다. `detail` 턴은 이 목록을 갱신하지 않습니다 — 새 목록을 보여준 턴이
아니라 이미 보여준 목록에서 하나를 설명한 턴이라, 지목된 한 건으로 갈아치우면 "아니 세 번째 것"
같은 연속 지목이 막힙니다.

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

- **검색 결과는 기본 5건**입니다. "3개만 찾아줘" 처럼 개수를 말하면 그 수만큼 돌려주고,
  관련 기록이 없으면 `results` 가 빈 배열입니다.
- **상세 답변의 근거는 본문 앞부분**입니다. 본문이 `DETAIL_MAX_CHARS` 를 넘으면 앞에서부터
  자르고(잘렸다는 사실은 프롬프트에 함께 알립니다), 질문과 맞물리는 구간을 골라 싣지는
  않습니다. 수집이 본문을 못 남긴 기록은 지어내지 않고 알려줄 수 없다고 답합니다.
- **지목할 수 있는 후보는 최근 대화 안에 있는 것뿐**입니다. 후보 목록은 프롬프트에 실린 범위
  (`CHAT_HISTORY_MESSAGES`, `CHAT_HISTORY_MAX_CHARS`)에서 찾으므로, 그보다 앞선 턴에서 보여준
  결과는 "두 번째 것" 으로 집을 수 없습니다.
- **`/batch` 는 자동 실행되지 않습니다.** 스케줄러가 없어 색인 시점을 직접 골라야 합니다.
- **CORS 가 전면 개방**되어 있습니다(`allow_origins=["*"]`). 확장 프로그램에서 직접
  호출하기 위한 설정이므로, 로컬 또는 신뢰된 네트워크 안에서만 띄우세요.
- **인증이 없습니다.** 열린 네트워크에 노출하면 누구나 방문 기록을 조회·삽입할 수 있습니다.
- **마이그레이션 도구가 없습니다.** 스키마는 `Base.metadata.create_all` 로만 생성되므로,
  이는 이미 있는 테이블에 컬럼을 더해주지 않습니다. 대부분의 모델 변경은 기존 DB(`app.db`)를
  지우고 다시 만들어야 합니다. 컬럼을 추가하는 경우처럼 기존 데이터(수집한 문서·임베딩 등,
  다시 만들려면 비용이 들거나 재수집이 불가능한 데이터)를 지킬 필요가 있으면, `init_db()`
  안에서 `PRAGMA table_info` 로 존재 여부를 확인하고 없을 때만 `ALTER TABLE` 로 더하는 식의
  1회성 마이그레이션을 직접 추가해야 합니다(`init_db._ensure_column` 이 그 자리이며,
  `conversations.title` 과 `messages.result_document_ids` 가 그렇게 더해진 컬럼입니다).
- 확장 프로그램 쪽 제약(시크릿 모드, SPA 본문 재추출)은
  [`extension/README.md`](extension/README.md) 에 정리되어 있습니다.
