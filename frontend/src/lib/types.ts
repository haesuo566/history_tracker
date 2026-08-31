export type ChatRole = "user" | "assistant";

/**
 * 백엔드 ChatResult 중 화면에서 실제로 쓰는 필드만 남긴 형태.
 * visitedAt 은 그 페이지를 본(수집한) 시각으로, 오프셋이 붙은 ISO 문자열이다. 날짜를 모르는
 * 기록도 있어 null 일 수 있다.
 */
export interface SearchResult {
  title: string;
  url: string;
  visitedAt: string | null;
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
 * client_now 는 오프셋이 붙은 브라우저의 현재 시각이다(lib/clock.ts). "어제 본 글" 같은 질의의
 * 하루 경계를 사용자의 자정으로 잡는 데 쓰이며, 서버는 이 값을 만들 수 없다.
 */
export interface ChatRequestBody {
  message: string;
  conversation_id?: string | null;
  client_now?: string;
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

/** 사이드바 목록 한 줄. GET /api/conversations 응답 본문의 원소다. */
export interface ConversationListItem {
  conversation_id: string;
  /** 메시지가 없는 대화는 제목이 없다(생성만 하고 쓰지 않은 경우). */
  title: string | null;
}

/** GET /api/conversations 응답 본문. */
export interface ConversationListBody {
  conversations: ConversationListItem[];
}

/**
 * GET /api/conversations/{id} 응답 본문.
 * 백엔드가 저장하는 것은 답변 문장과 그 턴이 보여준 document_id 뿐이지만, 조회할 때 문서를 조인해
 * 제목과 URL 을 되살려 주므로 다시 불러온 대화에도 결과 카드가 함께 온다.
 * 결과가 없던 턴, 그리고 그 id 가 저장되기 전에 쌓인 옛 메시지는 results 가 빈 배열이다.
 */
export interface ConversationDetailBody {
  conversation_id: string;
  messages: { role: string; content: string; results: SearchResult[] }[];
}

/** 설정 화면의 모델 선택지 한 줄. 임베딩 제공자 선택지도 같은 형태다. */
export interface ModelOption {
  id: string;
  label: string;
}

/** 임베딩을 어디서 받아오는지. 백엔드 EmbeddingProvider 와 같은 값이다. */
export type EmbeddingProvider = "gemini" | "tei";

/**
 * GET·PATCH /api/settings 응답 본문. 백엔드 SettingsResponse 를 그대로 옮긴 형태다.
 *
 * 다른 응답들과 달리 camelCase 로 바꾸지 않는다. 여덟 필드 전부를 화면이 쓰므로 버릴 것이 없고,
 * 경계마다 이름만 바꿔 옮기면 필드를 더할 때 고칠 자리가 늘기만 한다.
 *
 * API key 원문은 이 응답에 없다. 저장돼 있는지(api_key_configured)와 끝 네 자리 힌트만 온다.
 */
export interface SettingsBody {
  answer_model: string;
  query_rewrite_model: string;
  embedding_model: string;
  embedding_provider: EmbeddingProvider;
  tei_base_url: string;
  /** TEI 는 서버에 올린 모델을 쓰므로 비워 둘 수 있다. */
  tei_model: string;
  /** Gemini 경로에서 요청하는 차원(.env 고정). TEI 경로에서는 쓰이지 않는다. */
  embedding_dim: number;
  /** 지금 색인에 들어 있는 벡터의 차원. 제공자를 바꿔 재색인했다면 위 값과 다르다. */
  indexed_dim: number;
  /** 지금 색인의 청크가 몇 글자로 잘려 있는지. */
  indexed_chunk_chars: number;
  /** 지금 설정대로 색인하면 쓸 청크 크기. TEI 는 서버에 물어야 알 수 있어 null 이다. */
  expected_chunk_chars: number | null;
  /** 색인을 다시 만들어야 지금 설정대로 동작하면 true. */
  reindex_required: boolean;
  /** 벡터 검색이 지금 동작하는지. false 면 본문 단어 검색만으로 답하고 있다. */
  vector_search_active: boolean;
  api_key_configured: boolean;
  api_key_hint: string | null;
  embedding_providers: ModelOption[];
  generation_models: ModelOption[];
  embedding_models: ModelOption[];
}

/**
 * PATCH /api/settings 요청 본문. 바꾸려는 항목만 담는다.
 * 화면은 저장된 API key 원문을 모르므로, 키를 새로 입력하지 않은 저장에서는 gemini_api_key 를
 * 아예 빼서 보낸다. 빈 문자열을 보내면 백엔드가 거부한다.
 */
export interface SettingsUpdateBody {
  answer_model?: string;
  query_rewrite_model?: string;
  embedding_model?: string;
  embedding_provider?: EmbeddingProvider;
  tei_base_url?: string;
  tei_model?: string;
  gemini_api_key?: string;
}

/**
 * POST /api/reindex 응답 본문.
 * 색인을 비우기만 하므로, 실제로 다시 쌓으려면 이어서 색인(POST /api/batch)을 돌려야 한다.
 */
export interface ReindexSummary {
  provider: string;
  dim: number;
  /** 앞으로 청크 하나에 담을 문자 수. */
  chunk_chars: number;
  /** 다시 쌓아야 하는 문서 수. */
  pending: number;
  /** 차원이 바뀌어 벡터 테이블을 다시 만들었는지. */
  recreated: boolean;
}
