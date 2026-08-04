export type ChatRole = "user" | "assistant";

/** 백엔드 ChatResult 중 화면에서 실제로 쓰는 필드만 남긴 형태. */
export interface SearchResult {
  title: string;
  url: string;
}

/**
 * assistant 응답은 recall 의도면 검색된 기록 목록(results), 그 외 의도면 자유 텍스트(answer)다.
 * 두 필드는 서로 독립적이라 동시에 존재할 수도 있으므로 있는 것을 모두 보여준다.
 * 둘 다 비어 있으면(results 빈 배열 + answer null) 못 찾은 것으로 취급한다.
 */
export type ChatMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; results: SearchResult[]; answer: string | null };

/**
 * POST /api/chat 요청 본문.
 * conversation_id 를 보내면 그 대화를 이어가고, 생략하거나 null 이면 새 대화가 시작된다.
 */
export interface ChatRequestBody {
  message: string;
  conversation_id?: string | null;
}

/**
 * POST /api/chat 응답 본문 (성공).
 * conversation_id 는 이번 요청이 실제로 사용한 대화다. 보낸 id 를 서버가 모르면 새로 시작된
 * 대화의 id 가 오므로, 응답을 받을 때마다 이 값으로 저장해 둔 id 를 갱신해야 한다.
 */
export interface ChatResponseBody {
  conversation_id: string;
  results: SearchResult[];
  answer: string | null;
}

/** 라우트 핸들러가 실패했을 때의 공통 응답 본문 */
export interface ErrorBody {
  message: string;
}

/** 백엔드 BatchResponse. POST /api/batch 의 응답 본문이기도 하다. */
export interface BatchSummary {
  attempted: number;
  succeeded: number;
  failed: number;
}
