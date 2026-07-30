"use client";

import { useCallback, useRef, useState } from "react";

import type { BatchSummary, ErrorBody } from "@/lib/types";

export type BatchStatus = "idle" | "running";

export function useBatch() {
  const [status, setStatus] = useState<BatchStatus>("idle");
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 색인이 오래 걸리는 동안 버튼을 여러 번 눌러도 요청이 겹치지 않게 한다.
  const runningRef = useRef(false);

  const dismiss = useCallback(() => {
    setSummary(null);
    setError(null);
  }, []);

  const run = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;

    setStatus("running");
    setSummary(null);
    setError(null);

    try {
      const response = await fetch("/api/batch", { method: "POST" });

      if (!response.ok) {
        const detail = await response
          .json()
          .then((payload: ErrorBody) => payload.message)
          .catch(() => null);
        throw new Error(detail ?? `요청이 실패했습니다 (${response.status}).`);
      }

      setSummary((await response.json()) as BatchSummary);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
    } finally {
      runningRef.current = false;
      setStatus("idle");
    }
  }, []);

  return { status, summary, error, run, dismiss };
}
