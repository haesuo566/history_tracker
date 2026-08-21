import { BackendError, resetIndex } from "@/lib/backend";

export const runtime = "nodejs";

function jsonError(message: string, status: number): Response {
  return Response.json({ message }, { status });
}

export async function POST(request: Request): Promise<Response> {
  try {
    const summary = await resetIndex(request.signal);
    return Response.json(summary, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      // 백엔드는 임베딩 제공자에 붙지 못하면 502 를 준다. 색인은 아직 그대로라는 점을 알려준다.
      if (error.status === 502) {
        return jsonError(
          "임베딩 서버에 연결하지 못해 재색인을 시작하지 못했습니다. 색인은 그대로입니다. TEI 주소와 서버 상태를 확인해 주세요.",
          502,
        );
      }
      return jsonError(error.message, 502);
    }
    console.error("[api/reindex] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}
