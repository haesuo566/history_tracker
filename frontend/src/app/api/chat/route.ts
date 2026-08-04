import type { NextRequest } from "next/server";

import { BackendError, searchHistory } from "@/lib/backend";
import type { ChatResponseBody } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60;

/** 백엔드로 넘기기 전에 잘라 낸다. 검색 질의로 이보다 길 이유가 없다. */
const MAX_MESSAGE_LENGTH = 2_000;

/** 서버가 발급하는 UUID 라 이보다 길면 우리가 준 값이 아니다. */
const MAX_CONVERSATION_ID_LENGTH = 100;

function jsonError(message: string, status: number): Response {
  return Response.json({ message }, { status });
}

type ParseResult = { message: string; conversationId: string | null } | { error: string };

function parseBody(body: unknown): ParseResult {
  if (typeof body !== "object" || body === null || !("message" in body)) {
    return { error: "message 필드가 필요합니다." };
  }

  const { message, conversation_id: conversationId } = body as {
    message: unknown;
    conversation_id?: unknown;
  };
  if (typeof message !== "string") {
    return { error: "message 는 문자열이어야 합니다." };
  }

  const trimmed = message.trim();
  if (trimmed.length === 0) {
    return { error: "message 는 비어 있을 수 없습니다." };
  }

  // 첫 요청에는 이어갈 대화가 없으므로 없거나 null 인 것이 정상이다.
  if (conversationId !== undefined && conversationId !== null && typeof conversationId !== "string") {
    return { error: "conversation_id 는 문자열이어야 합니다." };
  }
  if (typeof conversationId === "string" && conversationId.length > MAX_CONVERSATION_ID_LENGTH) {
    return { error: "conversation_id 가 너무 깁니다." };
  }

  return {
    message: trimmed.slice(0, MAX_MESSAGE_LENGTH),
    conversationId: typeof conversationId === "string" && conversationId.length > 0 ? conversationId : null,
  };
}

export async function POST(request: NextRequest): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonError("요청 본문이 올바른 JSON이 아닙니다.", 400);
  }

  const parsed = parseBody(body);
  if ("error" in parsed) {
    return jsonError(parsed.error, 400);
  }

  try {
    const { conversationId, results, answer } = await searchHistory(
      parsed.message,
      parsed.conversationId,
      request.signal,
    );
    const payload: ChatResponseBody = { conversation_id: conversationId, results, answer };
    return Response.json(payload, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    // 사용자가 탭을 닫거나 중단한 경우. 보낼 곳이 없으므로 조용히 끝낸다.
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    if (error instanceof BackendError) {
      return jsonError(error.message, 502);
    }
    console.error("[api/chat] request failed", error);
    return jsonError("알 수 없는 오류가 발생했습니다.", 500);
  }
}
