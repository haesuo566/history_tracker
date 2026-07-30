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

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("idle");
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
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
      const requestBody: ChatRequestBody = { message: text };
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

      const { result } = (await response.json()) as ChatResponseBody;
      setMessages((previous) => [
        ...previous,
        { id: createId(), role: "assistant", result },
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
