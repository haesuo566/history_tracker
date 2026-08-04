"use client";

import { useCallback, useRef, useState } from "react";

import type {
  ChatMessage,
  ChatRequestBody,
  ChatResponseBody,
  ErrorBody,
} from "@/lib/types";

export type ChatStatus = "idle" | "loading";

function createId(): string {
  return crypto.randomUUID();
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  /**
   * 이어가는 중인 대화. 서버가 발급한 값을 응답마다 받아서 갱신한다.
   * 렌더링에 쓰이지 않고 send 안에서만 읽으므로, 의존성 때문에 값이 낡지 않도록 state 가 아닌 ref 로 둔다.
   */
  const conversationIdRef = useRef<string | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("idle");
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    // id 를 버리면 다음 요청에서 서버가 새 대화를 시작한다. 이전 대화는 서버에 그대로 남는다.
    conversationIdRef.current = null;
    setMessages([]);
    setError(null);
    setStatus("idle");
  }, []);

  const send = useCallback(async (input: string) => {
    const text = input.trim();
    if (text.length === 0 || abortRef.current !== null) return;

    setError(null);
    setStatus("loading");
    setMessages((previous) => [
      ...previous,
      { id: createId(), role: "user", content: text },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const requestBody: ChatRequestBody = {
        message: text,
        conversation_id: conversationIdRef.current,
      };
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });

      if (!response.ok) {
        const detail = await response
          .json()
          .then((payload: ErrorBody) => payload.message)
          .catch(() => null);
        throw new Error(detail ?? `요청이 실패했습니다 (${response.status}).`);
      }

      const { conversation_id, results, answer } = (await response.json()) as ChatResponseBody;

      // 응답을 기다리는 사이 reset() 이 이 요청을 무효화했으면, 비운 화면에 답변을 되살리거나
      // 버린 대화의 id 를 복구해서는 안 된다.
      if (abortRef.current !== controller) return;

      conversationIdRef.current = conversation_id;
      setMessages((previous) => [
        ...previous,
        { id: createId(), role: "assistant", results, answer },
      ]);
    } catch (caught) {
      // 중단은 오류가 아니다. 응답 말풍선을 추가하지 않고 그대로 끝낸다.
      if (caught instanceof Error && caught.name === "AbortError") return;
      setError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
    } finally {
      abortRef.current = null;
      setStatus("idle");
    }
  }, []);

  return { messages, status, error, send, stop, reset };
}
