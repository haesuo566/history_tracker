export type ChatRole = "user" | "assistant";

/** 백엔드 ChatResult 중 화면에서 실제로 쓰는 필드만 남긴 형태. */
export interface SearchResult {
  title: string;
  url: string;
}

/**
 * assistant 응답은 자유 텍스트가 아니라 검색된 기록 한 건이다.
 * 찾지 못한 경우를 result: null 로 구분한다.
 */
export type ChatMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; result: SearchResult | null };

/** POST /api/chat 요청 본문 */
export interface ChatRequestBody {
  message: string;
}

/** POST /api/chat 응답 본문 (성공) */
export interface ChatResponseBody {
  result: SearchResult | null;
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
