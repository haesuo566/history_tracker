import { BackendError, deleteConversation, getConversation, renameConversation } from "@/lib/backend";
import type { ConversationDetailBody } from "@/lib/types";

export const runtime = "nodejs";

type RouteContext = { params: Promise<{ id: string }> };

function jsonError(message: string, status: number): Response {
  return Response.json({ message }, { status });
}

export async function GET(request: Request, { params }: RouteContext): Promise<Response> {
  const { id } = await params;

  try {
    const messages = await getConversation(id, request.signal);
    if (messages === null) {
      return jsonError("대화를 찾을 수 없습니다.", 404);
    }

    const payload: ConversationDetailBody = { conversation_id: id, messages };
    return Response.json(payload, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      return jsonError(error.message, 502);
    }
    console.error("[api/conversations/:id GET] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}

export async function PATCH(request: Request, { params }: RouteContext): Promise<Response> {
  const { id } = await params;

  let title: string;
  try {
    const body = (await request.json()) as Record<string, unknown>;
    if (typeof body.title !== "string" || body.title.trim().length === 0) {
      return jsonError("제목을 입력해 주세요.", 400);
    }
    title = body.title;
  } catch {
    return jsonError("요청 본문을 해석할 수 없습니다.", 400);
  }

  try {
    const renamed = await renameConversation(id, title, request.signal);
    if (!renamed) {
      return jsonError("대화를 찾을 수 없습니다.", 404);
    }
    return new Response(null, { status: 204 });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      return jsonError(error.message, 502);
    }
    console.error("[api/conversations/:id PATCH] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}

export async function DELETE(request: Request, { params }: RouteContext): Promise<Response> {
  const { id } = await params;

  try {
    const deleted = await deleteConversation(id, request.signal);
    if (!deleted) {
      return jsonError("대화를 찾을 수 없습니다.", 404);
    }
    return new Response(null, { status: 204 });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      return jsonError(error.message, 502);
    }
    console.error("[api/conversations/:id DELETE] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}
