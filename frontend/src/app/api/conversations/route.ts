import { BackendError, listConversations } from "@/lib/backend";
import type { ConversationListBody } from "@/lib/types";

export const runtime = "nodejs";

function jsonError(message: string, status: number): Response {
  return Response.json({ message }, { status });
}

export async function GET(request: Request): Promise<Response> {
  try {
    const conversations = await listConversations(request.signal);
    const payload: ConversationListBody = {
      conversations: conversations.map((item) => ({
        conversation_id: item.conversationId,
        title: item.title,
      })),
    };
    return Response.json(payload, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      return jsonError(error.message, 502);
    }
    console.error("[api/conversations] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}
