import type { BatchSummary, SearchResult } from "@/lib/types";

/** FastAPI 백엔드 주소. 라우트 핸들러(서버)에서만 읽으므로 NEXT_PUBLIC_ 접두사가 필요 없다. */
const BASE_URL = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

/** 쿼리 재작성 + 임베딩 + 검색이 순차로 일어나 수 초까지 걸릴 수 있다. */
const SEARCH_TIMEOUT_MS = 30_000;

/** 미처리 문서 전체를 청크로 나눠 임베딩하므로 분 단위로 걸릴 수 있다. */
const BATCH_TIMEOUT_MS = 10 * 60_000;

/** 백엔드 호출 실패를 사용자에게 보여줄 문구와 함께 전달한다. */
export class BackendError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BackendError";
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
  const timeout = AbortSignal.timeout(timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
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

  if (!response.ok) {
    throw new BackendError(`백엔드가 오류를 반환했습니다 (${response.status}).`);
  }

  try {
    return await response.json();
  } catch {
    throw new BackendError("백엔드 응답을 해석할 수 없습니다.");
  }
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
  results: SearchResult[];
  answer: string | null;
}

/**
 * POST /chat 으로 질의한다. recall 의도면 results 에 관련 기록 목록(없으면 빈 배열)이,
 * 그 외 의도면 answer 에 자유 텍스트 응답이 담겨 온다.
 */
export async function searchHistory(
  message: string,
  signal?: AbortSignal,
): Promise<ChatReply> {
  const payload = await postJson("/chat", {
    body: { message },
    timeoutMs: SEARCH_TIMEOUT_MS,
    signal,
  });

  const { results: rawResults, answer: rawAnswer } = payload as Record<string, unknown>;

  const results = Array.isArray(rawResults)
    ? rawResults
        .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
        .map(toSearchResult)
        .filter((result): result is SearchResult => result !== null)
    : [];

  const answer = typeof rawAnswer === "string" && rawAnswer.length > 0 ? rawAnswer : null;

  return { results, answer };
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
