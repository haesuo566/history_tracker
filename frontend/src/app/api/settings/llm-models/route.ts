import { BackendError, listLlmModels } from "@/lib/backend";
import type { LlmModelsBody } from "@/lib/types";

export const runtime = "nodejs";

function jsonError(message: string, status: number): Response {
  return Response.json({ message }, { status });
}

/**
 * OpenAI 호환 서버에 올라가 있는 모델 이름들. base_url 을 주면 아직 저장하지 않은 주소로 묻는다.
 * 실패해도 화면은 모델 이름을 직접 입력할 수 있으므로, 사유만 돌려주고 막지는 않는다.
 */
export async function GET(request: Request): Promise<Response> {
  const baseUrl = new URL(request.url).searchParams.get("base_url")?.trim() || null;
  if (baseUrl !== null && !/^https?:\/\//.test(baseUrl)) {
    return jsonError("서버 주소는 http:// 또는 https:// 로 시작해야 합니다.", 400);
  }

  try {
    const payload: LlmModelsBody = { models: await listLlmModels(baseUrl, request.signal) };
    return Response.json(payload, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      // 주소를 아직 저장하지 않았는데 base_url 도 없으면 백엔드가 422 로 거절한다.
      if (error.status === 422) {
        return jsonError("서버 주소를 입력해 주세요.", 400);
      }
      return jsonError(error.message, 502);
    }
    console.error("[api/settings/llm-models GET] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}
