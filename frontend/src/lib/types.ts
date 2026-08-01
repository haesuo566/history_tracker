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

/** POST /api/chat 요청 본문 */
export interface ChatRequestBody {
  message: string;
}

/** POST /api/chat 응답 본문 (성공) */
export interface ChatResponseBody {
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
