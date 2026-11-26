import { BackendError, getSettings, updateSettings } from "@/lib/backend";
import type { SettingsUpdateBody } from "@/lib/types";

export const runtime = "nodejs";

function jsonError(message: string, status: number): Response {
  return Response.json({ message }, { status });
}

export async function GET(request: Request): Promise<Response> {
  try {
    const settings = await getSettings(request.signal);
    return Response.json(settings, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      return jsonError(error.message, 502);
    }
    console.error("[api/settings GET] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}

const MODEL_FIELDS = ["generation_model", "embedding_model"] as const;

/**
 * 넘어온 항목만 추려서 백엔드로 보낸다.
 * 어떤 모델 id 가 유효한지는 백엔드의 상수 목록이 정하므로 여기서는 형태만 본다. 다만 빈 문자열은
 * 여기서 걸러낸다 — 화면이 빈 값을 보내면 백엔드는 422 로 거절하는데, 그 사유를 사용자가 읽을 수
 * 있는 문구로 바꿀 자리가 여기다.
 */
function toUpdates(body: Record<string, unknown>): SettingsUpdateBody | string {
  const updates: SettingsUpdateBody = {};

  for (const field of MODEL_FIELDS) {
    const value = body[field];
    if (value === undefined || value === null) continue;
    if (typeof value !== "string" || value.length === 0) {
      return "모델을 선택해 주세요.";
    }
    updates[field] = value;
  }

  const generationProvider = body.generation_provider;
  if (generationProvider !== undefined && generationProvider !== null) {
    if (generationProvider !== "gemini" && generationProvider !== "openai_compat") {
      return "생성 모델 제공자를 선택해 주세요.";
    }
    updates.generation_provider = generationProvider;
  }

  const llmBaseUrl = body.llm_base_url;
  if (llmBaseUrl !== undefined && llmBaseUrl !== null) {
    if (typeof llmBaseUrl !== "string" || llmBaseUrl.trim().length === 0) {
      return "생성 모델 서버 주소를 입력해 주세요.";
    }
    const trimmed = llmBaseUrl.trim();
    if (!/^https?:\/\//.test(trimmed)) {
      return "생성 모델 서버 주소는 http:// 또는 https:// 로 시작해야 합니다.";
    }
    updates.llm_base_url = trimmed;
  }

  // 서버에 무엇이 올라가 있는지는 그 서버만 알아 목록으로 검증할 수 없다. 비었는지만 본다.
  const llmModel = body.llm_model;
  if (llmModel !== undefined && llmModel !== null) {
    if (typeof llmModel !== "string" || llmModel.trim().length === 0) {
      return "생성 모델 이름을 입력해 주세요.";
    }
    updates.llm_model = llmModel.trim();
  }

  // Gemini 키와 달리 빈 문자열은 '지우기'라 그대로 넘긴다.
  const llmApiKey = body.llm_api_key;
  if (typeof llmApiKey === "string") {
    updates.llm_api_key = llmApiKey.trim();
  }

  const disableThinking = body.llm_disable_thinking;
  if (typeof disableThinking === "boolean") {
    updates.llm_disable_thinking = disableThinking;
  }

  const provider = body.embedding_provider;
  if (provider !== undefined && provider !== null) {
    if (provider !== "gemini" && provider !== "tei") {
      return "임베딩 제공자를 선택해 주세요.";
    }
    updates.embedding_provider = provider;
  }

  const baseUrl = body.tei_base_url;
  if (baseUrl !== undefined && baseUrl !== null) {
    if (typeof baseUrl !== "string" || baseUrl.trim().length === 0) {
      return "TEI 주소를 입력해 주세요.";
    }
    const trimmed = baseUrl.trim();
    if (!/^https?:\/\//.test(trimmed)) {
      return "TEI 주소는 http:// 또는 https:// 로 시작해야 합니다.";
    }
    updates.tei_base_url = trimmed;
  }

  // 모델명은 TEI 가 검증하지 않는 표시용 값이라 비워 두는 것도 정당하다.
  const teiModel = body.tei_model;
  if (typeof teiModel === "string") {
    updates.tei_model = teiModel.trim();
  }

  const apiKey = body.gemini_api_key;
  if (apiKey !== undefined && apiKey !== null) {
    if (typeof apiKey !== "string" || apiKey.trim().length === 0) {
      return "API key 를 입력해 주세요.";
    }
    updates.gemini_api_key = apiKey.trim();
  }

  return updates;
}

export async function PATCH(request: Request): Promise<Response> {
  let updates: SettingsUpdateBody;
  try {
    const parsed = toUpdates((await request.json()) as Record<string, unknown>);
    if (typeof parsed === "string") {
      return jsonError(parsed, 400);
    }
    updates = parsed;
  } catch {
    return jsonError("요청 본문을 해석할 수 없습니다.", 400);
  }

  try {
    const settings = await updateSettings(updates, request.signal);
    return Response.json(settings, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      // 422 는 백엔드가 값을 검증해서 거절한 것이다. 502(백엔드 장애)로 뭉개면 사용자는 다시
      // 시도하면 될 일로 읽는다.
      if (error.status === 422) {
        return jsonError(
          "설정값을 저장할 수 없습니다. 선택한 모델, 서버 주소, API key 를 확인해 주세요.",
          400,
        );
      }
      return jsonError(error.message, 502);
    }
    console.error("[api/settings PATCH] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}
