import type { NextRequest } from "next/server";

import { BackendError, runBatch } from "@/lib/backend";
import type { BatchSummary } from "@/lib/types";

export const runtime = "nodejs";
// 미처리 문서가 많으면 색인에 분 단위로 걸린다. 짧게 두면 서버리스 환경에서 잘린다.
export const maxDuration = 300;

function jsonError(message: string, status: number): Response {
  return Response.json({ message }, { status });
}

export async function POST(request: NextRequest): Promise<Response> {
  try {
    const summary: BatchSummary = await runBatch(request.signal);
    return Response.json(summary, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    // 사용자가 탭을 닫거나 중단한 경우. 보낼 곳이 없으므로 조용히 끝낸다.
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      return jsonError(error.message, 502);
    }
    console.error("[api/batch] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}
