"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ErrorBody, ReindexSummary, SettingsBody, SettingsUpdateBody } from "@/lib/types";

export type SettingsStatus = "loading" | "ready" | "saving" | "reindexing" | "failed";

async function readError(response: Response): Promise<string> {
  const detail = await response
    .json()
    .then((payload: ErrorBody) => payload.message)
    .catch(() => null);
  return detail ?? `요청이 실패했습니다 (${response.status}).`;
}

/**
 * 설정을 불러오고 저장한다.
 *
 * 저장은 PATCH 응답에 담겨 오는 갱신된 설정으로 화면 상태를 갈아끼운다. 화면이 보낸 값을 그대로
 * 믿고 표시하면, 백엔드가 실제로 무엇을 쓰고 있는지와 화면이 어긋날 수 있다.
 */
export function useSettings() {
  const [settings, setSettings] = useState<SettingsBody | null>(null);
  const [status, setStatus] = useState<SettingsStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [isSaved, setIsSaved] = useState(false);

  // 저장이 오래 걸리는 동안 버튼을 여러 번 눌러도 요청이 겹치지 않게 한다.
  const savingRef = useRef(false);

  // status/error 초기값이 이미 "loading"/null 이므로 마운트 시 호출은 그 값을 그대로 쓴다.
  // 여기서 상태를 먼저 건드리면 effect 안에서 동기 setState 를 하는 셈이 된다(useChatSessions
  // 의 fetchSessions 와 같은 이유다). 재시도처럼 상태를 되돌려야 하는 경로만 따로 처리한다.
  const fetchSettings = useCallback((signal: AbortSignal) => {
    fetch("/api/settings", { signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(await readError(response));
        return (await response.json()) as SettingsBody;
      })
      .then((loaded) => {
        setSettings(loaded);
        setStatus("ready");
      })
      .catch((caught) => {
        if (caught instanceof Error && caught.name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
        setStatus("failed");
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchSettings(controller.signal);
    return () => controller.abort();
  }, [fetchSettings]);

  const retry = useCallback(() => {
    setStatus("loading");
    setError(null);
    fetchSettings(new AbortController().signal);
  }, [fetchSettings]);

  const save = useCallback(async (updates: SettingsUpdateBody): Promise<boolean> => {
    if (savingRef.current) return false;
    savingRef.current = true;

    setStatus("saving");
    setError(null);
    setIsSaved(false);

    try {
      const response = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      if (!response.ok) throw new Error(await readError(response));

      setSettings((await response.json()) as SettingsBody);
      setIsSaved(true);
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
      return false;
    } finally {
      savingRef.current = false;
      setStatus("ready");
    }
  }, []);

  /**
   * 색인을 비우고 모든 문서를 색인 대기로 되돌린다. 되돌릴 수 없다.
   *
   * 성공하면 설정을 다시 불러온다 — 재색인이 끝나면 reindex_required 가 내려가는데, 그 사실은
   * 이 응답에 담겨 오지 않는다.
   */
  const reindex = useCallback(async (): Promise<ReindexSummary | null> => {
    if (savingRef.current) return null;
    savingRef.current = true;

    setStatus("reindexing");
    setError(null);
    setIsSaved(false);

    try {
      const response = await fetch("/api/reindex", { method: "POST" });
      if (!response.ok) throw new Error(await readError(response));

      const summary = (await response.json()) as ReindexSummary;
      const refreshed = await fetch("/api/settings");
      if (refreshed.ok) setSettings((await refreshed.json()) as SettingsBody);
      return summary;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "알 수 없는 오류가 발생했습니다.");
      return null;
    } finally {
      savingRef.current = false;
      setStatus("ready");
    }
  }, []);

  /** 사용자가 값을 다시 만지면 저장 완료 표시를 내린다. */
  const clearSavedMark = useCallback(() => setIsSaved(false), []);

  return { settings, status, error, isSaved, save, reindex, retry, clearSavedMark };
}
