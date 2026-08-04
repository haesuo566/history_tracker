# Conversations API

`/chat`으로 오간 대화를 나중에 찾아보거나 정리하기 위한 엔드포인트 3개.
라우트는 `backend/src/backend/api/routes/conversation.py`, 실제 로직은
`backend/src/backend/services/conversation.py`에 있다.

## 개념

| 개념 | 설명 |
| --- | --- |
| `conversations` | 대화 세션. `conversation_id`(UUID), `created_at`, `title` |
| `messages` | 대화에 오간 메시지 한 건. `role`(`user`/`assistant`), `content`, `created_at`. 순서는 `created_at`이 아니라 내부 `id`로 판단한다(초 단위라 같은 요청의 user/assistant가 같은 값을 가질 수 있어서) |

**`title`은 사용자가 정하는 값이 아니다.** 그 대화의 **첫 `user` 메시지**가 저장되는 시점에
한 번만 자동으로 채워지고(`services/conversation.py`의 `append_message`), 이후 메시지가 더
쌓여도 바뀌지 않는다. 매 목록 조회마다 메시지를 다시 훑지 않기 위한 캐시 값이라 이렇게
설계했다. 규칙:

- 개행·연속 공백은 한 칸으로 접는다.
- 60자를 넘으면 60자에서 자르고 말줄임표(`…`)를 붙인다. 컬럼 길이도 `VARCHAR(61)`로 이에 맞춰져 있다.
- 접은 결과가 빈 문자열이면(공백뿐인 메시지) `title`을 채우지 않는다 — 메시지가 없는 대화와
  마찬가지로 `null`로 남는다.

## `/chat`과의 관계

`POST /chat`은 `conversation_id`를 안 보내거나 모르는 값을 보내면 **알아서 새 대화를 열고**
그 id를 응답에 담아준다. 클라이언트는 그 값을 저장해뒀다가 다음 요청에 실어 보내면 대화가
이어진다. 대화를 미리 여는 별도 엔드포인트는 없다 — 프론트가 그 id를 응답 전에 먼저 쥐어야
할 이유가 없고, 미리 열어두면 첫 메시지 없이 `title`이 `null`인 빈 대화가 목록에 남는 문제만
생기기 때문이다.

---

## `GET /conversations`

대화 목록을 **최근 활동 순**으로 반환한다.

**쿼리 파라미터**

| 이름 | 기본값 | 범위 |
| --- | --- | --- |
| `limit` | `50` | `1`–`200` |

범위를 벗어나면 `422`:

```json
{
  "detail": [
    {
      "type": "greater_than_equal",
      "loc": ["query", "limit"],
      "msg": "Input should be greater than or equal to 1",
      "input": "0",
      "ctx": { "ge": 1 }
    }
  ]
}
```

**응답 `200`**

```json
{
  "conversations": [
    {
      "conversation_id": "f856011a-3e2b-4ee9-b270-0bfc37042e10",
      "title": "어제 본 리액트 상태관리 글 찾아줘",
      "message_count": 2,
      "created_at": "2026-08-04T14:01:52",
      "last_message_at": "2026-08-04T14:01:53"
    },
    {
      "conversation_id": "27042152-ceec-4e4f-ac9b-a57c5d08db57",
      "title": null,
      "message_count": 0,
      "created_at": "2026-08-04T14:01:36",
      "last_message_at": null
    }
  ]
}
```

`message_count`와 `last_message_at`은 `title`과 달리 컬럼으로 두지 않고 매번 `messages`를
집계해서 구한다.

### 정렬 규칙

기준은 `last_message_at` — 메시지가 없는 대화는 이 값이 없으므로 `created_at`으로 대신한다.
두 시각 모두 초 단위라 같은 초에 몰린 대화끼리는 갈리지 않으므로, 뒤 기준으로 메시지의
내부 `id`(단조 증가)를, 그래도 갈리지 않으면 대화의 내부 `id`를 쓴다.

이 규칙 때문에 **오래된 대화를 다시 이어가면 방금 만든 대화보다 위로 올라온다** — 목록은
생성 순이 아니라 활동 순이다.

---

## `GET /conversations/{conversation_id}`

대화 한 건의 전체 메시지를 반환한다. `/chat`이 컨텍스트로 쓰는
`load_recent_messages`(최근 N건만, `settings.chat_history_messages`)와 달리 **잘라내지 않는다**
— 화면에 대화를 그대로 복원하는 용도라서다.

**응답 `200`**

```json
{
  "conversation_id": "f856011a-3e2b-4ee9-b270-0bfc37042e10",
  "created_at": "2026-08-04T14:01:52",
  "messages": [
    {
      "role": "user",
      "content": "어제 본 리액트 상태관리 글 찾아줘",
      "created_at": "2026-08-04T14:01:53"
    },
    {
      "role": "assistant",
      "content": "이 글입니다: https://example.com/react-state",
      "created_at": "2026-08-04T14:01:53"
    }
  ]
}
```

메시지가 없으면 `"messages": []`. 오래된 것부터 시간순.

**모르는 `conversation_id`면 `404`**

```json
{ "detail": "conversation not found" }
```

---

## `DELETE /conversations/{conversation_id}`

대화와 그 안의 메시지를 전부 지운다.

**응답**: 성공하면 `204`(본문 없음). 모르는 id면 `404`(`GET` 상세와 같은 본문).

`Message.conversation_id`는 FK로 선언돼 있지만, SQLite는 `PRAGMA foreign_keys=ON` 없이는
이를 강제하지 않고 이 프로젝트도 그 설정을 켜지 않는다. 그래서 서버 코드가 `messages`를
먼저 명시적으로 지운 뒤 `conversations` 행을 지운다(`delete_conversation`) — 순서를 반대로
하거나 messages 삭제를 빼면 고아 행이 남아 조회는 안 되지만 자리만 차지한다.

---

## 구현 메모

- 스키마 마이그레이션 도구가 없다(`Base.metadata.create_all`은 이미 있는 테이블에 컬럼을
  더해주지 않는다). `title` 컬럼은 기존 `app.db`(재수집 불가능한 문서·비용이 든 임베딩 포함)를
  지우지 않기 위해 `db/init_db.py`의 `_ensure_conversations_title_column`이 `PRAGMA table_info`로
  존재를 확인하고 없을 때만 `ALTER TABLE`로 추가한다.
- 테스트: `backend/tests/test_conversation_route.py`(라우트 단위), `test_conversation.py`(서비스
  단위 일부).
