import type {
  BatchSummary,
  ModelOption,
  ReindexSummary,
  SearchResult,
  SettingsBody,
  SettingsUpdateBody,
} from "@/lib/types";

/** FastAPI 백엔드 주소. 라우트 핸들러(서버)에서만 읽으므로 NEXT_PUBLIC_ 접두사가 필요 없다. */
const BASE_URL = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

/** 쿼리 재작성 + 임베딩 + 검색이 순차로 일어나 수 초까지 걸릴 수 있다. */
const SEARCH_TIMEOUT_MS = 30_000;

/** 미처리 문서 전체를 청크로 나눠 임베딩하므로 분 단위로 걸릴 수 있다. */
const BATCH_TIMEOUT_MS = 10 * 60_000;

/** 대화 목록/조회/삭제는 단순 DB 조회라 오래 걸릴 이유가 없다. */
const CONVERSATION_TIMEOUT_MS = 10_000;

/** 설정 조회/저장도 DB만 건드린다. */
const SETTINGS_TIMEOUT_MS = 10_000;

/**
 * 재색인은 색인을 비우는 것까지만 하지만, 그 전에 임베딩 제공자를 한 번 불러 차원을 확인한다.
 * TEI 가 막 떠서 모델을 올리는 중이면 그 한 번이 오래 걸릴 수 있다.
 */
const REINDEX_TIMEOUT_MS = 60_000;

/**
 * 백엔드 호출 실패를 사용자에게 보여줄 문구와 함께 전달한다.
 * status 는 백엔드가 응답은 했으나 오류였을 때의 상태 코드다. 연결 실패·타임아웃이면 없다.
 */
export class BackendError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "BackendError";
    this.status = status;
  }
}

interface RequestOptions {
  method: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  timeoutMs: number;
  signal?: AbortSignal;
  /** 404 를 오류로 던지지 않고 null 로 돌려준다(예: 모르는 conversation_id 조회/삭제). */
  treatNotFoundAsNull?: boolean;
}

/**
 * 백엔드에 요청하고 JSON 을 돌려준다.
 * body 를 생략하면 본문 없이 보낸다(예: /batch 는 요청 값이 없다).
 * 응답 본문이 없는 204 는 undefined 를, treatNotFoundAsNull 인 404 는 null 을 돌려준다.
 */
async function request(
  path: string,
  { method, body, timeoutMs, signal, treatNotFoundAsNull }: RequestOptions,
): Promise<unknown> {
  const timeout = AbortSignal.timeout(timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      ...(body === undefined
        ? {}
        : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
      signal: signal === undefined ? timeout : AbortSignal.any([signal, timeout]),
      cache: "no-store",
    });
  } catch (error) {
    // 사용자가 중단한 경우는 호출한 쪽에서 구분해야 하므로 그대로 던진다.
    if (signal?.aborted === true) throw error;
    if (timeout.aborted) {
      throw new BackendError("백엔드 응답이 너무 오래 걸립니다. 다시 시도해 주세요.");
    }
    throw new BackendError(
      `백엔드(${BASE_URL})에 연결할 수 없습니다. 서버가 실행 중인지 확인해 주세요.`,
    );
  }

  if (response.status === 404 && treatNotFoundAsNull === true) {
    return null;
  }
  if (!response.ok) {
    throw new BackendError(`백엔드가 오류를 반환했습니다 (${response.status}).`, response.status);
  }
  if (response.status === 204) {
    return undefined;
  }

  try {
    return await response.json();
  } catch {
    throw new BackendError("백엔드 응답을 해석할 수 없습니다.");
  }
}

/**
 * 백엔드로 POST 하고 JSON 을 돌려준다.
 * body 를 생략하면 본문 없이 보낸다(예: /batch 는 요청 값이 없다).
 */
async function postJson(
  path: string,
  { body, timeoutMs, signal }: { body?: unknown; timeoutMs: number; signal?: AbortSignal },
): Promise<unknown> {
  return request(path, { method: "POST", body, timeoutMs, signal });
}

/**
 * 백엔드 ChatResult 에는 document_id, score 도 있지만 화면에서 쓰지 않기로 했으므로
 * 이 경계에서 버려서 클라이언트까지 내려가지 않게 한다.
 */
function toSearchResult(raw: Record<string, unknown>): SearchResult | null {
  const { title, url } = raw;
  if (typeof title !== "string" || typeof url !== "string" || url.length === 0) {
    return null;
  }
  // 제목이 비어 있는 문서도 있어 링크 텍스트가 사라지지 않도록 URL 로 대체한다.
  return { title: title.length > 0 ? title : url, url };
}

export interface ChatReply {
  conversationId: string;
  results: SearchResult[];
  answer: string | null;
}

/**
 * POST /chat 으로 질의한다. recall 의도면 results 에 관련 기록 목록(없으면 빈 배열)이,
 * 그 외 의도면 answer 에 자유 텍스트 응답이 담겨 온다.
 * conversationId 를 넘기면 그 대화를 이어가고, null 이면 새 대화가 시작된다.
 */
export async function searchHistory(
  message: string,
  conversationId: string | null,
  signal?: AbortSignal,
): Promise<ChatReply> {
  const payload = await postJson("/chat", {
    body: { message, conversation_id: conversationId },
    timeoutMs: SEARCH_TIMEOUT_MS,
    signal,
  });

  const {
    conversation_id: rawConversationId,
    results: rawResults,
    answer: rawAnswer,
  } = payload as Record<string, unknown>;

  // id 를 못 받으면 다음 질문이 조용히 새 대화로 시작돼 맥락이 끊긴다. 조용히 넘기지 않는다.
  if (typeof rawConversationId !== "string" || rawConversationId.length === 0) {
    throw new BackendError("백엔드가 예상과 다른 형식을 반환했습니다.");
  }

  const results = Array.isArray(rawResults)
    ? rawResults
        .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
        .map(toSearchResult)
        .filter((result): result is SearchResult => result !== null)
    : [];

  const answer = typeof rawAnswer === "string" && rawAnswer.length > 0 ? rawAnswer : null;

  return { conversationId: rawConversationId, results, answer };
}

function toCount(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

/** POST /batch 로 미처리 문서 색인을 실행하고 처리 건수를 받는다. 요청 값은 없다. */
export async function runBatch(signal?: AbortSignal): Promise<BatchSummary> {
  const payload = await postJson("/batch", { timeoutMs: BATCH_TIMEOUT_MS, signal });

  const { attempted, succeeded, failed } = payload as Record<string, unknown>;
  const counts = [toCount(attempted), toCount(succeeded), toCount(failed)];
  if (counts.some((count) => count === null)) {
    throw new BackendError("백엔드가 예상과 다른 형식을 반환했습니다.");
  }

  const [a, s, f] = counts as number[];
  return { attempted: a, succeeded: s, failed: f };
}

export interface ConversationSummaryItem {
  conversationId: string;
  /** 메시지가 없는 대화는 제목이 없다. */
  title: string | null;
}

/**
 * 백엔드 ConversationSummary 에는 message_count, created_at, last_message_at 도 있지만
 * 사이드바 목록에서 쓰지 않으므로 이 경계에서 버린다.
 */
function toConversationSummary(raw: Record<string, unknown>): ConversationSummaryItem | null {
  const { conversation_id: conversationId, title } = raw;
  if (typeof conversationId !== "string" || conversationId.length === 0) return null;
  return { conversationId, title: typeof title === "string" ? title : null };
}

/** GET /conversations 로 대화 목록을 최근 활동 순으로 받는다. */
export async function listConversations(signal?: AbortSignal): Promise<ConversationSummaryItem[]> {
  const payload = await request("/conversations", {
    method: "GET",
    timeoutMs: CONVERSATION_TIMEOUT_MS,
    signal,
  });

  const { conversations } = payload as Record<string, unknown>;
  if (!Array.isArray(conversations)) {
    throw new BackendError("백엔드가 예상과 다른 형식을 반환했습니다.");
  }

  return conversations
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map(toConversationSummary)
    .filter((item): item is ConversationSummaryItem => item !== null);
}

export interface ConversationMessageItem {
  role: "user" | "assistant";
  content: string;
}

function toConversationMessage(raw: Record<string, unknown>): ConversationMessageItem | null {
  const { role, content } = raw;
  if (role !== "user" && role !== "assistant") return null;
  if (typeof content !== "string") return null;
  return { role, content };
}

/**
 * GET /conversations/{id} 로 대화 전문을 받는다. 모르는 id 면 null.
 * 과거 assistant 메시지는 Gemini 가 생성한 답변 문장만 저장돼 있고 검색 결과(title/url)는
 * DB에 남지 않으므로, 다시 불러온 assistant 메시지에는 결과 카드가 없다.
 */
export async function getConversation(
  conversationId: string,
  signal?: AbortSignal,
): Promise<ConversationMessageItem[] | null> {
  const payload = await request(`/conversations/${encodeURIComponent(conversationId)}`, {
    method: "GET",
    timeoutMs: CONVERSATION_TIMEOUT_MS,
    signal,
    treatNotFoundAsNull: true,
  });
  if (payload === null) return null;

  const { messages } = payload as Record<string, unknown>;
  if (!Array.isArray(messages)) {
    throw new BackendError("백엔드가 예상과 다른 형식을 반환했습니다.");
  }

  return messages
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map(toConversationMessage)
    .filter((item): item is ConversationMessageItem => item !== null);
}

/** PATCH /conversations/{id} 로 제목을 바꾼다. 이미 없는 대화면 false. */
export async function renameConversation(
  conversationId: string,
  title: string,
  signal?: AbortSignal,
): Promise<boolean> {
  const result = await request(`/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    body: { title },
    timeoutMs: CONVERSATION_TIMEOUT_MS,
    signal,
    treatNotFoundAsNull: true,
  });
  return result !== null;
}

function toModelOptions(value: unknown): ModelOption[] | null {
  if (!Array.isArray(value)) return null;

  const options: ModelOption[] = [];
  for (const item of value) {
    if (typeof item !== "object" || item === null) return null;
    const { id, label } = item as Record<string, unknown>;
    if (typeof id !== "string" || id.length === 0 || typeof label !== "string") return null;
    options.push({ id, label });
  }
  return options;
}

/**
 * 백엔드 SettingsResponse 를 형태만 확인해서 그대로 돌려준다.
 * 선택 상자를 그릴 수 없는 응답(모델 목록이 비었거나 형태가 다름)은 오류로 본다 — 빈 선택 상자를
 * 보여주면 사용자가 고를 수 없는데도 저장 버튼은 눌리는 화면이 된다.
 */
function toSettings(payload: unknown): SettingsBody {
  const raw = payload as Record<string, unknown>;
  const generationModels = toModelOptions(raw.generation_models);
  const embeddingModels = toModelOptions(raw.embedding_models);
  const providers = toModelOptions(raw.embedding_providers);
  const provider = raw.embedding_provider;

  if (
    typeof raw.answer_model !== "string" ||
    typeof raw.query_rewrite_model !== "string" ||
    typeof raw.embedding_model !== "string" ||
    (provider !== "gemini" && provider !== "tei") ||
    typeof raw.tei_base_url !== "string" ||
    typeof raw.tei_model !== "string" ||
    typeof raw.embedding_dim !== "number" ||
    typeof raw.indexed_dim !== "number" ||
    typeof raw.indexed_chunk_chars !== "number" ||
    typeof raw.reindex_required !== "boolean" ||
    typeof raw.vector_search_active !== "boolean" ||
    typeof raw.api_key_configured !== "boolean" ||
    generationModels === null ||
    generationModels.length === 0 ||
    embeddingModels === null ||
    embeddingModels.length === 0 ||
    providers === null ||
    providers.length === 0
  ) {
    throw new BackendError("백엔드가 예상과 다른 형식을 반환했습니다.");
  }

  return {
    answer_model: raw.answer_model,
    query_rewrite_model: raw.query_rewrite_model,
    embedding_model: raw.embedding_model,
    embedding_provider: provider,
    tei_base_url: raw.tei_base_url,
    tei_model: raw.tei_model,
    embedding_dim: raw.embedding_dim,
    indexed_dim: raw.indexed_dim,
    indexed_chunk_chars: raw.indexed_chunk_chars,
    expected_chunk_chars:
      typeof raw.expected_chunk_chars === "number" ? raw.expected_chunk_chars : null,
    reindex_required: raw.reindex_required,
    vector_search_active: raw.vector_search_active,
    api_key_configured: raw.api_key_configured,
    api_key_hint: typeof raw.api_key_hint === "string" ? raw.api_key_hint : null,
    embedding_providers: providers,
    generation_models: generationModels,
    embedding_models: embeddingModels,
  };
}

/** GET /settings 로 현재 설정과 선택지를 받는다. */
export async function getSettings(signal?: AbortSignal): Promise<SettingsBody> {
  const payload = await request("/settings", {
    method: "GET",
    timeoutMs: SETTINGS_TIMEOUT_MS,
    signal,
  });
  return toSettings(payload);
}

/**
 * PATCH /settings 로 넘긴 항목만 저장하고 갱신된 설정을 받는다.
 * 백엔드가 저장 후의 설정 전체를 돌려주므로 저장 직후 다시 조회할 필요가 없다.
 */
export async function updateSettings(
  updates: SettingsUpdateBody,
  signal?: AbortSignal,
): Promise<SettingsBody> {
  const payload = await request("/settings", {
    method: "PATCH",
    body: updates,
    timeoutMs: SETTINGS_TIMEOUT_MS,
    signal,
  });
  return toSettings(payload);
}

/**
 * POST /reindex 로 색인을 비우고 모든 문서를 색인 대기로 되돌린다.
 * 되돌릴 수 없다. 실제로 다시 쌓는 것은 이어서 부르는 runBatch 다.
 */
export async function resetIndex(signal?: AbortSignal): Promise<ReindexSummary> {
  const payload = await postJson("/reindex", { timeoutMs: REINDEX_TIMEOUT_MS, signal });

  const { provider, dim, chunk_chars: chunkChars, pending, recreated } = payload as Record<string, unknown>;
  if (
    typeof provider !== "string" ||
    typeof dim !== "number" ||
    typeof chunkChars !== "number" ||
    toCount(pending) === null ||
    typeof recreated !== "boolean"
  ) {
    throw new BackendError("백엔드가 예상과 다른 형식을 반환했습니다.");
  }

  return { provider, dim, chunk_chars: chunkChars, pending: pending as number, recreated };
}

/** DELETE /conversations/{id} 로 대화를 지운다. 이미 없는 대화면 false. */
export async function deleteConversation(conversationId: string, signal?: AbortSignal): Promise<boolean> {
  const result = await request(`/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    timeoutMs: CONVERSATION_TIMEOUT_MS,
    signal,
    treatNotFoundAsNull: true,
  });
  return result !== null;
}
