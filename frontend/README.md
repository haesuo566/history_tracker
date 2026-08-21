# 검색 기록 찾기

Next.js 16 App Router 로 만든 채팅 UI. 자연어로 물어보면 FastAPI 백엔드가 내 검색/열람 기록에서
가장 관련 있는 페이지 한 건을 찾아 줍니다.

## 시작하기

1. 백엔드 실행 — 저장소 루트의 `backend/` 에서 띄웁니다.

   ```bash
   uvicorn backend.main:app --reload
   ```

2. 백엔드 주소 설정 (선택) — 기본값은 `http://127.0.0.1:8000` 입니다. 다른 곳이면 `.env.local` 에 넣습니다.

   ```
   BACKEND_URL=http://127.0.0.1:8000
   ```

3. 개발 서버 실행

   ```bash
   npm run dev
   ```

   http://localhost:3000 접속.

환경변수 목록은 `.env.example` 참고.

## 구조

```
src/
  app/
    api/chat/route.ts      요청 검증 후 백엔드 /chat 으로 프록시
    api/batch/route.ts     색인 트리거를 백엔드 /batch 로 프록시
    api/conversations/     대화 목록·조회·이름변경·삭제 프록시
    api/settings/route.ts  설정 조회·저장 프록시
    api/reindex/route.ts   색인 비우기 프록시
    layout.tsx             전체 화면 레이아웃 (입력창 하단 고정)
    page.tsx               채팅 페이지
    settings/page.tsx      설정 페이지 (모델 선택, API key)
    globals.css            Tailwind + 테마 변수
  components/chat/
    ChatContainer.tsx      입력 상태 + 헤더/사이드바/목록/입력창 조합
    ChatSidebar.tsx        대화 목록, 이름 바꾸기·삭제
    MessageList.tsx        스크롤 컨테이너, 빈 상태, 예시 질문
    MessageBubble.tsx      말풍선 (AI 응답은 링크 카드)
    ChatInput.tsx          자동 높이 textarea, Enter 전송, 중단 버튼
    BatchControl.tsx       색인 버튼과 결과 배너
  components/settings/
    SettingsForm.tsx       설정 폼과 헤더
  hooks/
    useChatSessions.ts     세션 목록, 메시지 히스토리, 요청/중단
    useBatch.ts            색인 실행 상태
    useSettings.ts         설정 조회·저장
  lib/
    backend.ts             백엔드 호출, 타임아웃, 필드 정리
    types.ts               공유 타입 (메시지, 검색 결과, 설정)
```

## 백엔드 연동

브라우저는 백엔드를 직접 부르지 않고 `/api/chat` 라우트 핸들러를 거칩니다. 백엔드 주소가
서버 쪽에만 있으면 되고, 응답 필드도 이 경계에서 한 번 정리됩니다.

```
브라우저  POST /api/chat        { "message": "어제 본 리액트 글" }
서버      POST {BACKEND_URL}/chat  { "message": "어제 본 리액트 글" }
```

백엔드 `ChatResult` 에는 `document_id` 와 `score` 도 있지만 화면에서 쓰지 않으므로
`lib/backend.ts` 에서 버리고 `title`, `url` 만 클라이언트로 내려보냅니다.

```
{ "result": { "title": "리액트 상태관리 정리", "url": "https://..." } }
{ "result": null }                                  // 관련 기록 없음
```

## 스크립트

| 명령 | 설명 |
| --- | --- |
| `npm run dev` | 개발 서버 |
| `npm run build` | 프로덕션 빌드 |
| `npm start` | 프로덕션 서버 |
| `npm run lint` | ESLint |
| `npx tsc --noEmit` | 타입 검사 |
